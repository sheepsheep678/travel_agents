"""用户长期记忆的 Milvus 向量层：稠密 + BM25 稀疏混合召回。

与知识库集合隔离（默认 ``user_memories``），只存跨会话的用户偏好、事实、
规则、任务结果和程序经验；会话摘要与任务状态仍存 PostgreSQL。

集合 schema 创建后不可改；改字段/维度/度量需 ``init_milvus --recreate``。
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, List, Optional, Sequence

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.integrations.llm import get_embedding_model
from backend.app.integrations.milvus import (
    MilvusUnavailableError,
    aembed_documents,
    get_milvus_client,
)

logger = get_logger(__name__)

_OUTPUT_FIELDS = [
    "id",
    "user_id",
    "kind",
    "city",
    "content",
    "text",
    "content_hash",
    "source_session_id",
    "importance",
    "confidence",
    "status",
    "created_at",
    "last_used_at",
]
_RRF_K = 60
_ready = False
_init_error = ""
_lock = threading.Lock()


def _collection() -> str:
    """返回长期记忆集合名。"""
    return settings.milvus.memory_collection


def _import_milvus():
    """延迟导入 pymilvus 类型，缺失时给出可读错误。"""
    try:
        from pymilvus import DataType, Function, FunctionType
    except Exception as exc:  # pragma: no cover
        raise MilvusUnavailableError(
            "pymilvus 未安装，请执行 pip install 'pymilvus>=3.0.3,<3.1'"
        ) from exc
    return DataType, Function, FunctionType


def _build_schema(client: Any):
    """构造长期记忆集合 schema：稠密 + BM25 稀疏 + 过滤字段。"""
    DataType, Function, FunctionType = _import_milvus()
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
    schema.add_field("user_id", DataType.VARCHAR, max_length=64)
    schema.add_field("kind", DataType.VARCHAR, max_length=32)
    schema.add_field("city", DataType.VARCHAR, max_length=64)
    schema.add_field("content", DataType.VARCHAR, max_length=4096)
    schema.add_field(
        "text",
        DataType.VARCHAR,
        max_length=4096,
        enable_analyzer=True,
        analyzer_params={"tokenizer": settings.milvus.analyzer_tokenizer},
    )
    schema.add_field("content_hash", DataType.VARCHAR, max_length=64)
    schema.add_field("source_session_id", DataType.VARCHAR, max_length=64)
    schema.add_field("importance", DataType.INT64)
    schema.add_field("confidence", DataType.FLOAT)
    schema.add_field("status", DataType.VARCHAR, max_length=16)
    schema.add_field("created_at", DataType.INT64)
    schema.add_field("last_used_at", DataType.INT64)
    schema.add_field("dense", DataType.FLOAT_VECTOR, dim=settings.milvus.dense_dim)
    schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
    schema.add_function(
        Function(
            name="bm25_memory_text",
            function_type=FunctionType.BM25,
            input_field_names=["text"],
            output_field_names=["sparse"],
        )
    )
    return schema


def _build_index_params():
    """稠密/稀疏/过滤字段索引。"""
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
    for field_name in ("id", "user_id", "kind", "city", "content_hash", "status"):
        index_params.add_index(field_name=field_name, index_type="INVERTED")
    return index_params


def init_memory_milvus(recreate: bool = False) -> bool:
    """初始化长期记忆集合；记忆功能关闭时直接返回就绪。"""
    global _ready, _init_error
    if not settings.memory.enabled or not settings.memory.long_term_enabled:
        _ready = True
        _init_error = ""
        return True

    collection = _collection()
    with _lock:
        try:
            client = get_milvus_client()
            if recreate and client.has_collection(collection):
                client.drop_collection(collection)
                logger.warning(
                    "Milvus 记忆集合已删除并准备重建", collection=collection
                )

            if not client.has_collection(collection):
                client.create_collection(
                    collection_name=collection,
                    schema=_build_schema(client),
                    index_params=_build_index_params(),
                )
                logger.info("Milvus 记忆集合已创建", collection=collection)

            client.load_collection(collection)
            _ready = True
            _init_error = ""
            return True
        except Exception as exc:
            _ready = False
            _init_error = str(exc)
            logger.exception("Milvus 记忆集合初始化失败", collection=collection)
            return False


def is_memory_milvus_ready() -> bool:
    """集合是否已就绪。"""
    return _ready


def memory_milvus_error() -> str:
    """最近一次初始化错误。"""
    return _init_error


def check_memory_milvus() -> bool:
    """健康检查：集合存在且可加载。"""
    if not settings.memory.enabled or not settings.memory.long_term_enabled:
        return True
    try:
        client = get_milvus_client()
        return client.has_collection(_collection())
    except Exception:
        return False


def memory_stats() -> dict:
    """集合统计（健康检查 / 调试 CLI 使用）。"""
    if not settings.memory.enabled or not settings.memory.long_term_enabled:
        return {"enabled": False, "collection": _collection(), "count": 0}
    try:
        client = get_milvus_client()
        rows = client.query(
            collection_name=_collection(),
            filter="",
            output_fields=["count(*)"],
        )
        count = 0
        if rows:
            row = rows[0]
            count = int(row.get("count(*)") or row.get("count") or 0)
        return {
            "enabled": True,
            "ready": _ready,
            "collection": _collection(),
            "count": count,
            "error": _init_error,
        }
    except Exception as exc:
        return {
            "enabled": True,
            "ready": False,
            "collection": _collection(),
            "count": 0,
            "error": str(exc),
        }


def _ensure_ready() -> Any:
    """返回可用客户端；进程内首次调用时自动建集合。"""
    client = get_milvus_client()
    if not _ready:
        if not init_memory_milvus():
            raise MilvusUnavailableError(
                _init_error or "Milvus 记忆集合未初始化，请先启动容器并执行 init_milvus"
            )
        client = get_milvus_client()
    return client


def _quote(value: Any) -> str:
    """转义 Milvus 表达式中的字符串字面量。"""
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _embed_query_sync(query: str) -> List[float]:
    """同步计算查询向量。"""
    return get_embedding_model().embed_query(query)


# ---------------------------------------------------------------------------
# 写入 / 删除
# ---------------------------------------------------------------------------


def _insert_rows_sync(rows: Sequence[dict]) -> int:
    """同步批量写入并 flush。"""
    if not rows:
        return 0
    client = _ensure_ready()
    collection = _collection()
    total = 0
    for start in range(0, len(rows), 100):
        batch = list(rows[start: start + 100])
        client.insert(collection, batch)
        total += len(batch)
    client.flush(collection)
    return total


async def ainsert_memories(rows: Sequence[dict]) -> int:
    """写入长期记忆；rows 需包含 text，dense 由本函数统一计算。"""
    rows = [dict(row) for row in rows]
    if not rows:
        return 0
    vectors = await aembed_documents([row["text"] for row in rows])
    for row, vector in zip(rows, vectors):
        row["dense"] = vector
    return await asyncio.to_thread(_insert_rows_sync, rows)


def _delete_sync(expr: str) -> int:
    """按过滤表达式同步删除并 flush。"""
    client = _ensure_ready()
    collection = _collection()
    result = client.delete(collection, filter=expr)
    try:
        client.flush(collection)
    except Exception:
        pass
    if isinstance(result, dict):
        return int(result.get("delete_count") or result.get("count") or 0)
    return 0


async def adelete_memory_ids(ids: Sequence[str], user_id: str) -> int:
    """按 id + user_id 精确删除，防止越权删除他人记忆。"""
    ids = [item for item in ids if item]
    if not ids or not user_id:
        return 0
    quoted = ", ".join(_quote(item) for item in ids)
    expr = f"user_id == {_quote(user_id)} and id in [{quoted}]"
    return await asyncio.to_thread(_delete_sync, expr)


async def adelete_user_memories(user_id: str) -> int:
    """清空一个用户的全部长期记忆。"""
    if not user_id:
        return 0
    return await asyncio.to_thread(
        _delete_sync, f"user_id == {_quote(user_id)}"
    )


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
    """稠密向量检索。"""
    client = _ensure_ready()
    result = client.search(
        collection_name=_collection(),
        data=[list(query_vector)],
        anns_field="dense",
        search_params={"metric_type": settings.milvus.dense_metric},
        limit=limit,
        filter=expr or "",
        output_fields=_OUTPUT_FIELDS,
    )
    return [_hit_to_dict(hit) for hit in (result[0] if result else [])]


def _search_sparse_sync(query: str, expr: str, limit: int) -> List[dict]:
    """BM25 稀疏检索。"""
    client = _ensure_ready()
    result = client.search(
        collection_name=_collection(),
        data=[query],
        anns_field="sparse",
        search_params={"metric_type": settings.milvus.sparse_metric},
        limit=limit,
        filter=expr or "",
        output_fields=_OUTPUT_FIELDS,
    )
    return [_hit_to_dict(hit) for hit in (result[0] if result else [])]


def _query_sync(expr: str, limit: int = 100) -> List[dict]:
    """同步标量查询。"""
    client = _ensure_ready()
    rows = client.query(
        collection_name=_collection(),
        filter=expr,
        output_fields=_OUTPUT_FIELDS,
        limit=limit,
    )
    return [dict(row) for row in (rows or [])]


async def aquery_memories(
    user_id: str,
    *,
    city: str = "",
    kind: str = "",
    limit: int = 100,
) -> List[dict]:
    """按用户列出记忆；city 为空时返回全部城市。"""
    if not user_id:
        return []
    expr = f"user_id == {_quote(user_id)}"
    if city:
        expr += f" and (city == \"\" or city == {_quote(city)})"
    if kind:
        expr += f" and kind == {_quote(kind)}"
    rows = await asyncio.to_thread(_query_sync, expr, max(1, int(limit)))
    rows.sort(key=lambda row: int(row.get("created_at") or 0), reverse=True)
    return rows


def _count_sync(expr: str) -> int:
    """同步统计满足条件的记录数。"""
    client = _ensure_ready()
    rows = client.query(
        collection_name=_collection(),
        filter=expr,
        output_fields=["count(*)"],
    )
    if not rows:
        return 0
    row = rows[0]
    return int(row.get("count(*)") or row.get("count") or 0)


async def acount_memories(
    user_id: str, *, city: str = "", status: str = "confirmed"
) -> int:
    """统计用户记忆条数；用于在无记忆时跳过 embedding 调用。"""
    if not user_id:
        return 0
    expr = f"user_id == {_quote(user_id)}"
    if status:
        expr += f" and status == {_quote(status)}"
    if city:
        expr += f" and (city == \"\" or city == {_quote(city)})"
    return await asyncio.to_thread(_count_sync, expr)


async def aquery_memory_by_hash(user_id: str, content_hash: str) -> List[dict]:
    """按内容哈希去重查询。"""
    if not user_id or not content_hash:
        return []
    expr = (
        f"user_id == {_quote(user_id)} and "
        f"content_hash == {_quote(content_hash)}"
    )
    return await asyncio.to_thread(_query_sync, expr, 1)


async def asearch_memories(
    user_id: str,
    query: str,
    *,
    city: str = "",
    limit: Optional[int] = None,
    min_importance: int = 0,
) -> List[dict]:
    """稠密 + BM25 多路召回 → RRF 融合；只召回 confirmed 记忆。"""
    query = (query or "").strip()
    if not user_id or not query:
        return []

    limit = max(1, int(limit or settings.memory.long_term_top_k))
    expr = f"user_id == {_quote(user_id)} and status == \"confirmed\""
    if min_importance > 0:
        expr += f" and importance >= {int(min_importance)}"
    if city:
        expr += f" and (city == \"\" or city == {_quote(city)})"

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

    dense_hits = [] if isinstance(dense_result, Exception) else list(dense_result or [])
    sparse_hits = [] if isinstance(sparse_result, Exception) else list(sparse_result or [])
    if isinstance(dense_result, Exception):
        logger.warning("记忆稠密检索失败", error=str(dense_result))
    if isinstance(sparse_result, Exception):
        logger.warning("记忆稀疏检索失败", error=str(sparse_result))
    if not dense_hits and not sparse_hits:
        return []

    merged: Dict[str, dict] = {}
    rrf: Dict[str, float] = {}
    for hits in (dense_hits, sparse_hits):
        for rank, hit in enumerate(hits):
            hit_id = str(hit.get("id") or "")
            if not hit_id:
                continue
            merged.setdefault(hit_id, dict(hit.get("entity") or {}))
            rrf[hit_id] = rrf.get(hit_id, 0.0) + 1.0 / (_RRF_K + rank + 1)

    results: List[dict] = []
    for hit_id, entity in merged.items():
        entity = dict(entity)
        entity["id"] = hit_id
        entity["score"] = rrf.get(hit_id, 0.0)
        results.append(entity)

    # RRF 之后用重要度做轻量加权，避免高重要度偏好被长尾结果挤掉
    results.sort(
        key=lambda row: (
            float(row.get("score") or 0.0)
            + int(row.get("importance") or 0) * 0.002,
            int(row.get("importance") or 0),
            int(row.get("created_at") or 0),
        ),
        reverse=True,
    )
    return results[:limit]
