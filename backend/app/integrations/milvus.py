"""Milvus 知识库向量层：稠密向量 + BM25 稀疏向量混合检索。

设计要点
--------
- 集合中只存**子块**（检索单元）；父块存 PostgreSQL，由
  ``modules/knowledge/retrieval.py`` 按 ``parent_id`` 回查后加入提示词。
- ``text`` 字段开启 jieba 分析器并绑定 BM25 Function，写入时只需提供
  ``text`` / ``dense``，稀疏向量由 Milvus 服务端自动生成（无需本地 BM25 模型）。
- 多路召回（dense + sparse）各自取候选，再用 DashScope ``gte-rerank``
  （Cross-Encoder）精排；精排不可用时回退 RRF 融合，保证检索不中断。
- 写入前先删除同一 ``doc_id`` 的旧向量，满足「先删再加」的幂等更新语义。
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.core.metrics import observe_rerank
from backend.app.integrations.llm import get_embedding_model

logger = get_logger(__name__)

# 输出字段：检索命中后用于构造提示词与调试
_OUTPUT_FIELDS = [
    "doc_id",
    "parent_id",
    "parent_index",
    "chunk_index",
    "scope",
    "owner_id",
    "visibility",
    "city",
    "title",
    "source",
    "source_type",
    "section",
    "block_type",
    "content_hash",
    "text",
    "content",
]

_EMBED_BATCH_SIZE = 10
_RRF_K = 60

_client: Any = None
_client_lock = threading.Lock()
_ready = False
_init_error = ""
# DashScope 精排失败（欠费/限流/网络）后短暂熔断，避免每条检索都重复请求
_rerank_disabled_until = 0.0
_RERANK_COOLDOWN_SECONDS = 300.0


class MilvusUnavailableError(RuntimeError):
    """Milvus 未安装 / 未启动 / 集合初始化失败。"""


# ---------------------------------------------------------------------------
# 客户端与集合初始化
# ---------------------------------------------------------------------------


def _import_milvus():
    try:
        from pymilvus import DataType, Function, FunctionType, MilvusClient
    except Exception as exc:  # pragma: no cover - 依赖缺失时给出可读错误
        raise MilvusUnavailableError(
            "pymilvus 未安装，请执行 pip install 'pymilvus>=3.0.3,<3.1'"
        ) from exc
    return DataType, Function, FunctionType, MilvusClient


def _make_client(db_name: str = "") -> Any:
    _, _, _, MilvusClient = _import_milvus()
    return MilvusClient(
        uri=settings.milvus.uri,
        token=settings.milvus.token or "",
        db_name=db_name,
        timeout=settings.milvus.connect_timeout,
    )


def get_milvus_client() -> Any:
    """惰性创建 MilvusClient 单例，并在非 default 库不存在时自动创建。"""
    global _client
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client

        db_name = (settings.milvus.db_name or "default").strip() or "default"
        if db_name != "default":
            admin = _make_client()
            try:
                if db_name not in admin.list_databases():
                    admin.create_database(db_name)
                    logger.info("Milvus 数据库已创建", database=db_name)
            finally:
                admin.close()

        _client = _make_client(db_name=db_name)
        logger.info(
            "Milvus 客户端已连接",
            uri=settings.milvus.uri,
            database=db_name,
            collection=settings.milvus.collection,
        )
        return _client


def _build_schema(client: Any):
    """构造子块集合 schema（字段 + BM25 Function）。"""
    DataType, Function, FunctionType, _ = _import_milvus()

    # 用 client.create_schema() 创建可增量 add_field 的 schema
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(
        "id", DataType.VARCHAR, is_primary=True, max_length=160
    )
    schema.add_field("doc_id", DataType.VARCHAR, max_length=64)
    schema.add_field("parent_id", DataType.VARCHAR, max_length=160)
    schema.add_field("parent_index", DataType.INT64)
    schema.add_field("chunk_index", DataType.INT64)
    schema.add_field("scope", DataType.VARCHAR, max_length=16)
    schema.add_field("owner_id", DataType.VARCHAR, max_length=64)
    schema.add_field("visibility", DataType.VARCHAR, max_length=16)
    schema.add_field("city", DataType.VARCHAR, max_length=64)
    schema.add_field("title", DataType.VARCHAR, max_length=256)
    schema.add_field("source", DataType.VARCHAR, max_length=256)
    schema.add_field("source_type", DataType.VARCHAR, max_length=16)
    schema.add_field("section", DataType.VARCHAR, max_length=512)
    schema.add_field("block_type", DataType.VARCHAR, max_length=32)
    schema.add_field("content_hash", DataType.VARCHAR, max_length=64)
    # 原始子块文本（不含标题前缀）
    schema.add_field("content", DataType.VARCHAR, max_length=8192)
    # 检索文本 = 文档标题 + 章节 + 原文，供 BM25 / 向量 / 精排使用
    schema.add_field(
        "text",
        DataType.VARCHAR,
        max_length=8192,
        enable_analyzer=True,
        analyzer_params={"tokenizer": settings.milvus.analyzer_tokenizer},
    )
    schema.add_field(
        "dense", DataType.FLOAT_VECTOR, dim=settings.milvus.dense_dim
    )
    schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
    schema.add_function(
        Function(
            name="bm25_text",
            function_type=FunctionType.BM25,
            input_field_names=["text"],
            output_field_names=["sparse"],
        )
    )
    return schema


def _build_index_params():
    from pymilvus.milvus_client import IndexParams

    index_params = IndexParams()
    index_params.add_index(
        field_name="dense",
        index_type="AUTOINDEX",
        metric_type=settings.milvus.dense_metric,
    )
    index_params.add_index(
        field_name="sparse",
        index_type="AUTOINDEX",
        metric_type=settings.milvus.sparse_metric,
    )
    # 过滤字段全部建 INVERTED 索引：scope / owner / city / doc / parent
    for field_name in (
        "id",
        "doc_id",
        "parent_id",
        "scope",
        "owner_id",
        "visibility",
        "city",
    ):
        index_params.add_index(field_name=field_name, index_type="INVERTED")
    return index_params


def init_milvus(recreate: bool = False) -> bool:
    """初始化数据库/集合/索引；返回是否就绪。"""
    global _ready, _init_error
    collection = settings.milvus.collection

    try:
        client = get_milvus_client()
        if recreate and client.has_collection(collection):
            client.drop_collection(collection)
            logger.warning("Milvus 集合已删除并准备重建", collection=collection)

        if not client.has_collection(collection):
            schema = _build_schema(client)
            index_params = _build_index_params()
            client.create_collection(
                collection_name=collection,
                schema=schema,
                index_params=index_params,
            )
            logger.info("Milvus 集合已创建", collection=collection)

        client.load_collection(collection)
        _ready = True
        _init_error = ""
        return True
    except Exception as exc:
        _ready = False
        _init_error = str(exc)
        logger.exception("Milvus 集合初始化失败", collection=collection)
        return False


def is_milvus_ready() -> bool:
    return _ready


def milvus_error() -> str:
    return _init_error


def check_milvus() -> bool:
    """健康检查：能连上并确认集合存在。"""
    try:
        client = get_milvus_client()
        client.get_server_version()
        return client.has_collection(settings.milvus.collection)
    except Exception:
        return False


def close_milvus() -> None:
    global _client, _ready
    if _client is not None:
        try:
            _client.close()
        except Exception:
            logger.warning("关闭 Milvus 客户端失败")
        _client = None
        _ready = False


def _ensure_ready() -> Any:
    client = get_milvus_client()
    if not _ready:
        # 进程内首次调用（例如 CLI）时自动建集合，而不是直接报错
        if not init_milvus():
            raise MilvusUnavailableError(
                _init_error or "Milvus 集合未初始化，请先启动容器并执行 init_milvus"
            )
        client = get_milvus_client()
    return client


# ---------------------------------------------------------------------------
# 向量化
# ---------------------------------------------------------------------------


def _embed_documents_sync(texts: Sequence[str]) -> List[List[float]]:
    embedding = get_embedding_model()
    vectors: List[List[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = list(texts[start: start + _EMBED_BATCH_SIZE])
        vectors.extend(embedding.embed_documents(batch))
    for vector in vectors:
        if len(vector) != settings.milvus.dense_dim:
            raise MilvusUnavailableError(
                "嵌入维度与 MILVUS_DENSE_DIM 不一致："
                f"实际 {len(vector)}，配置 {settings.milvus.dense_dim}。"
                "修改维度后需删除集合并重建。"
            )
    return vectors


async def aembed_documents(texts: Sequence[str]) -> List[List[float]]:
    if not texts:
        return []
    return await asyncio.to_thread(_embed_documents_sync, list(texts))


def _embed_query_sync(query: str) -> List[float]:
    return get_embedding_model().embed_query(query)


# ---------------------------------------------------------------------------
# 写入 / 删除
# ---------------------------------------------------------------------------


def _insert_rows_sync(rows: Sequence[dict]) -> int:
    if not rows:
        return 0
    client = _ensure_ready()
    collection = settings.milvus.collection
    total = 0
    for start in range(0, len(rows), 100):
        batch = list(rows[start: start + 100])
        client.insert(collection, batch)
        total += len(batch)
    # 立即 flush，保证紧随其后的检索 / 校验能看到数据
    client.flush(collection)
    return total


async def ainsert_children(rows: Sequence[dict]) -> int:
    """插入子块；rows 需包含 text，dense 由本函数统一计算后回填。"""
    rows = [dict(row) for row in rows]
    texts = [row["text"] for row in rows]
    vectors = await aembed_documents(texts)
    for row, vector in zip(rows, vectors):
        row["dense"] = vector
    return await asyncio.to_thread(_insert_rows_sync, rows)


def _delete_filter_sync(expr: str) -> int:
    client = _ensure_ready()
    collection = settings.milvus.collection
    result = client.delete(collection, filter=expr)
    try:
        client.flush(collection)
    except Exception:
        pass
    if isinstance(result, dict):
        return int(result.get("delete_count") or result.get("count") or 0)
    return 0


async def adelete_where(expr: str) -> int:
    if not expr or not expr.strip():
        raise ValueError("拒绝执行空过滤条件的删除")
    return await asyncio.to_thread(_delete_filter_sync, expr)


def _quote(value: Any) -> str:
    """Milvus 表达式字符串字面量转义。"""
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


async def adelete_document(doc_id: str, owner_id: str, scope: str) -> int:
    """删除一个文档的全部子块（先删再加的删）。"""
    expr = (
        f"doc_id == {_quote(doc_id)} and "
        f"owner_id == {_quote(owner_id)} and "
        f"scope == {_quote(scope)}"
    )
    try:
        return await adelete_where(expr)
    except MilvusUnavailableError:
        raise
    except Exception as exc:
        logger.warning(
            "删除 Milvus 文档子块失败", doc_id=doc_id, owner_id=owner_id, error=str(exc)
        )
        raise


async def adelete_ids(ids: Sequence[str]) -> int:
    if not ids:
        return 0
    quoted = ", ".join(_quote(i) for i in ids)
    return await adelete_where(f"id in [{quoted}]")


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------


def _hit_to_dict(hit: Any) -> dict:
    """兼容 pymilvus 不同版本的 Hit 对象 / dict 返回。"""
    if isinstance(hit, dict):
        entity = hit.get("entity") or {}
        if not isinstance(entity, dict):
            entity = dict(entity)
        hit_id = hit.get("id") or entity.get("id")
        score = hit.get("distance", hit.get("score", 0.0))
    else:
        entity_obj = getattr(hit, "entity", None)
        if entity_obj is None:
            entity = {}
        elif isinstance(entity_obj, dict):
            entity = dict(entity_obj)
        else:
            entity = dict(entity_obj) if hasattr(entity_obj, "__iter__") else {}
        hit_id = getattr(hit, "id", None) or entity.get("id")
        score = getattr(hit, "score", getattr(hit, "distance", 0.0))
    return {"id": str(hit_id or ""), "score": float(score or 0.0), "entity": entity}


def _search_dense_sync(
    query_vector: Sequence[float], expr: str, limit: int
) -> List[dict]:
    client = _ensure_ready()
    result = client.search(
        collection_name=settings.milvus.collection,
        data=[list(query_vector)],
        anns_field="dense",
        search_params={"metric_type": settings.milvus.dense_metric},
        limit=limit,
        filter=expr or "",
        output_fields=_OUTPUT_FIELDS,
    )
    return [_hit_to_dict(hit) for hit in (result[0] if result else [])]


def _search_sparse_sync(query: str, expr: str, limit: int) -> List[dict]:
    client = _ensure_ready()
    result = client.search(
        collection_name=settings.milvus.collection,
        data=[query],
        anns_field="sparse",
        search_params={"metric_type": settings.milvus.sparse_metric},
        limit=limit,
        filter=expr or "",
        output_fields=_OUTPUT_FIELDS,
    )
    return [_hit_to_dict(hit) for hit in (result[0] if result else [])]


@dataclass
class RetrievalHit:
    id: str
    text: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    dense_score: float = 0.0
    sparse_score: float = 0.0
    fusion_score: float = 0.0
    rerank_score: Optional[float] = None
    retrieval: str = ""

    @property
    def score(self) -> float:
        if self.rerank_score is not None:
            return self.rerank_score
        return self.fusion_score

    @property
    def parent_id(self) -> str:
        return str(self.metadata.get("parent_id") or "")

    @property
    def doc_id(self) -> str:
        return str(self.metadata.get("doc_id") or "")


def _merge_candidates(
    dense_hits: Sequence[dict], sparse_hits: Sequence[dict]
) -> Dict[str, RetrievalHit]:
    merged: Dict[str, RetrievalHit] = {}

    def _add(hit: dict, route: str) -> None:
        entity = hit.get("entity") or {}
        metadata = dict(entity)
        hit_id = hit["id"] or str(metadata.get("id") or "")
        text = str(metadata.get("text") or "")
        content = str(metadata.get("content") or text)
        item = merged.get(hit_id)
        if item is None:
            item = RetrievalHit(id=hit_id, text=text, content=content, metadata=metadata)
            merged[hit_id] = item
        if route == "dense":
            item.dense_score = max(item.dense_score, float(hit.get("score") or 0.0))
        else:
            item.sparse_score = max(item.sparse_score, float(hit.get("score") or 0.0))
        if item.retrieval and route not in item.retrieval:
            item.retrieval = "hybrid"
        elif not item.retrieval:
            item.retrieval = route

    for hit in dense_hits:
        _add(hit, "dense")
    for hit in sparse_hits:
        _add(hit, "sparse")
    return merged


def _rrf_scores(
    dense_hits: Sequence[dict], sparse_hits: Sequence[dict]
) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for hits in (dense_hits, sparse_hits):
        for rank, hit in enumerate(hits):
            hit_id = str(hit.get("id") or "")
            if not hit_id:
                continue
            scores[hit_id] = scores.get(hit_id, 0.0) + 1.0 / (_RRF_K + rank + 1)
    return scores


def _rerank_sync(query: str, documents: Sequence[str], top_n: int) -> List[dict]:
    import dashscope
    from dashscope import TextReRank

    dashscope.api_key = settings.llm.api_key
    response = TextReRank.call(
        model=settings.milvus.rerank_model,
        query=query,
        documents=list(documents),
        top_n=top_n,
        return_documents=False,
        api_key=settings.llm.api_key,
    )
    status_code = getattr(response, "status_code", 200)
    if status_code != 200:
        raise RuntimeError(
            f"rerank 调用失败: {getattr(response, 'message', status_code)}"
        )
    output = getattr(response, "output", None) or {}
    results = output.get("results") if isinstance(output, dict) else None
    return list(results or [])


async def _rerank(
    query: str, hits: Sequence[RetrievalHit], top_n: int
) -> Optional[List[RetrievalHit]]:
    global _rerank_disabled_until
    if not settings.milvus.rerank_enabled or not hits:
        observe_rerank("disabled")
        return None
    if time.time() < _rerank_disabled_until:
        observe_rerank("circuit_open")
        return None

    candidates = list(hits)[: settings.milvus.rerank_max_candidates]
    documents = [hit.text or hit.content for hit in candidates]
    top_n = max(1, min(int(top_n or len(documents)), len(documents)))
    try:
        results = await asyncio.to_thread(_rerank_sync, query, documents, top_n)
    except Exception as exc:
        _rerank_disabled_until = time.time() + _RERANK_COOLDOWN_SECONDS
        observe_rerank("circuit_breaker")
        logger.warning(
            "Cross-Encoder 精排失败，回退 RRF 融合（熔断 %ss）",
            int(_RERANK_COOLDOWN_SECONDS),
            error=str(exc),
        )
        return None
    observe_rerank("ok")

    reranked: List[RetrievalHit] = []
    for item in results:
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(candidates):
            continue
        hit = candidates[index]
        hit.rerank_score = float(item.get("relevance_score") or 0.0)
        reranked.append(hit)
    reranked.sort(key=lambda h: h.rerank_score or 0.0, reverse=True)
    return reranked


async def ahybrid_search(
    query: str,
    *,
    expr: str = "",
    limit: Optional[int] = None,
) -> List[RetrievalHit]:
    """多路召回（dense + BM25 sparse）→ RRF 融合 → Cross-Encoder 精排。"""
    if not query.strip():
        return []
    limit = limit or settings.milvus.final_top_k
    query_vector = await asyncio.to_thread(_embed_query_sync, query)

    dense_task = asyncio.to_thread(
        _search_dense_sync,
        query_vector,
        expr,
        settings.milvus.dense_candidates,
    )
    sparse_task = asyncio.to_thread(
        _search_sparse_sync,
        query,
        expr,
        settings.milvus.sparse_candidates,
    )
    dense_result, sparse_result = await asyncio.gather(
        dense_task, sparse_task, return_exceptions=True
    )

    dense_hits: List[dict] = []
    sparse_hits: List[dict] = []
    if isinstance(dense_result, Exception):
        logger.warning("Milvus 稠密检索失败", error=str(dense_result))
    else:
        dense_hits = list(dense_result or [])
    if isinstance(sparse_result, Exception):
        logger.warning("Milvus 稀疏检索失败", error=str(sparse_result))
    else:
        sparse_hits = list(sparse_result or [])

    if not dense_hits and not sparse_hits:
        if isinstance(dense_result, Exception) and isinstance(sparse_result, Exception):
            raise MilvusUnavailableError(
                f"Milvus 混合检索失败: {dense_result}; {sparse_result}"
            )
        return []

    merged = _merge_candidates(dense_hits, sparse_hits)
    rrf = _rrf_scores(dense_hits, sparse_hits)
    for hit_id, hit in merged.items():
        hit.fusion_score = rrf.get(hit_id, 0.0)

    candidates = sorted(merged.values(), key=lambda h: h.fusion_score, reverse=True)
    reranked = await _rerank(query, candidates, settings.milvus.rerank_top_n or limit)
    if reranked:
        logger.info(
            "Milvus 混合检索完成（精排）",
            dense=len(dense_hits),
            sparse=len(sparse_hits),
            candidates=len(candidates),
            returned=len(reranked[:limit]),
        )
        return reranked[:limit]

    logger.info(
        "Milvus 混合检索完成（RRF）",
        dense=len(dense_hits),
        sparse=len(sparse_hits),
        candidates=len(candidates),
        returned=len(candidates[:limit]),
    )
    return candidates[:limit]


def _query_sync(expr: str, output_fields: Sequence[str], limit: int = 100) -> List[dict]:
    client = _ensure_ready()
    return list(
        client.query(
            collection_name=settings.milvus.collection,
            filter=expr,
            output_fields=list(output_fields),
            limit=limit,
        )
        or []
    )


async def aquery(
    expr: str, output_fields: Sequence[str] = _OUTPUT_FIELDS, limit: int = 100
) -> List[dict]:
    return await asyncio.to_thread(_query_sync, expr, output_fields, limit)


def _count_sync(expr: str) -> int:
    client = _ensure_ready()
    # Milvus 3.x 不允许 count(*) 与分页 limit 同时出现
    rows = client.query(
        collection_name=settings.milvus.collection,
        filter=expr,
        output_fields=["count(*)"],
    )
    if not rows:
        return 0
    row = rows[0]
    return int(row.get("count(*)") or row.get("count") or 0)


async def acount(expr: str = "") -> int:
    return await asyncio.to_thread(_count_sync, expr)


def _get_by_ids_sync(ids: Sequence[str]) -> List[dict]:
    if not ids:
        return []
    quoted = ", ".join(_quote(i) for i in ids)
    return _query_sync(f"id in [{quoted}]", _OUTPUT_FIELDS, limit=len(ids))


async def aget_by_ids(ids: Sequence[str]) -> List[dict]:
    return await asyncio.to_thread(_get_by_ids_sync, list(ids))


def stats() -> dict:
    """集合统计（健康检查 / 调试 CLI 使用）。"""
    try:
        return {
            "ready": _ready,
            "uri": settings.milvus.uri,
            "database": settings.milvus.db_name,
            "collection": settings.milvus.collection,
            "count": _count_sync(""),
            "error": _init_error,
        }
    except Exception as exc:
        return {
            "ready": False,
            "uri": settings.milvus.uri,
            "database": settings.milvus.db_name,
            "collection": settings.milvus.collection,
            "count": 0,
            "error": str(exc),
        }
