"""向量检索评测：多数据集 + 难负例 + nDCG / 延迟 / 成本 + HyDE 消融。

数据集
------
- ``base``：``datasets/retrieval_eval.jsonl``，100 对基础 query/文档（冻结）。
- ``hard``：``datasets/retrieval_eval_hard.jsonl``，同城不同景点、跨城同名景点、
  长文档（自动走父子块切分）与模糊 query。
- ``all``：两者合并。

评测集合独立于生产知识库（默认写入 Milvus ``default`` 库），不会污染
``travel/knowledge_chunks``。切换数据集时使用不同集合名，互不覆盖。

用法（仓库根目录）：
    python -m backend.app.evaluation.retrieval_eval
    python -m backend.app.evaluation.retrieval_eval --dataset hard --hyde both
    python -m backend.app.evaluation.retrieval_eval --dataset all --no-rerank --limit 20
    python -m backend.app.evaluation.retrieval_eval --dataset hard --rebuild

结果保存到 ``backend/app/evaluation/results/retrieval_eval_<时间>.json``；
管理端通过 ``--output`` 指定路径后直接读取该文件。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.agent.prompts import RAG_HYDE_SYSTEM, build_rag_hyde_user
from backend.app.core.config import settings
from backend.app.core.logging import get_logger, setup_logging
from backend.app.core.metrics import estimate_tokens
from backend.app.integrations.llm import get_fast_llm
from backend.app.integrations.milvus import (
    _embed_query_sync,
    _search_dense_sync,
    _search_sparse_sync,
    acount,
    ahybrid_search,
    ainsert_children,
    get_milvus_client,
    init_milvus,
)
from backend.app.modules.knowledge.chunking import chunk_parent_child

logger = get_logger(__name__)

_EVAL_DIR = Path(__file__).parent
_DATASETS = {
    "base": _EVAL_DIR / "datasets" / "retrieval_eval.jsonl",
    "hard": _EVAL_DIR / "datasets" / "retrieval_eval_hard.jsonl",
}
_RESULTS = _EVAL_DIR / "results"
_EVAL_DB = os.getenv("RETRIEVAL_EVAL_DB", "default")
_COLLECTIONS = {
    "base": os.getenv("RETRIEVAL_EVAL_COLLECTION", "retrieval_eval"),
    "hard": os.getenv("RETRIEVAL_EVAL_HARD_COLLECTION", "retrieval_eval_hard"),
    "all": os.getenv("RETRIEVAL_EVAL_ALL_COLLECTION", "retrieval_eval_all"),
}
_DATASET_NAMES = ("base", "hard", "all")
_MODES = ("dense", "sparse", "hybrid")
_LONG_DOC_THRESHOLD = 1200
_MAX_TEXT_CHARS = 8000
# 导入时先记住生产集合名，避免评测配置误指到生产集合后被 --rebuild 删除
_PRODUCTION_COLLECTION = (
    os.getenv("MILVUS_COLLECTION") or settings.milvus.collection or "knowledge_chunks"
).strip()


# ---------------------------------------------------------------------------
# 数据集与入库
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL 并跳过空行。"""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _dataset_files(dataset: str) -> list[Path]:
    """返回数据集对应的源文件（all 为 base + hard）。"""
    if dataset == "all":
        return [_DATASETS["base"], _DATASETS["hard"]]
    return [_DATASETS[dataset]]


def load_pairs(dataset: str = "base", limit: int = 0) -> list[dict[str, Any]]:
    """读取 query/文档评测集；limit 只截断本轮评测的 query。"""
    rows: list[dict[str, Any]] = []
    for path in _dataset_files(dataset):
        rows.extend(_read_jsonl(path))
    return rows[:limit] if limit and limit > 0 else rows


def dataset_sha256(dataset: str) -> str:
    """固定评测集的 SHA256，用于确认文本未被改动。"""
    digest = hashlib.sha256()
    for path in _dataset_files(dataset):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def collection_for(dataset: str) -> str:
    """评测集合名：base / hard / all 各自独立。"""
    return _COLLECTIONS.get(dataset) or f"retrieval_eval_{dataset}"


def configure_eval_target(dataset: str) -> str:
    """把 Milvus 指向独立评测库/集合，避免误用生产知识库。"""
    collection = collection_for(dataset)
    if collection == _PRODUCTION_COLLECTION:
        raise RuntimeError(
            f"评测集合名 {collection!r} 与生产 MILVUS_COLLECTION 相同，拒绝执行"
        )
    settings.milvus.db_name = _EVAL_DB
    settings.milvus.collection = collection
    return collection


def _marker_path(dataset: str) -> Path:
    """每个集合对应一份入库标记。"""
    return _RESULTS / f"retrieval_eval_ingested_{collection_for(dataset)}.json"


def _read_marker(dataset: str) -> dict:
    """读取入库标记（数据集哈希、文档数、行数）。"""
    try:
        return json.loads(_marker_path(dataset).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_marker(dataset: str, documents: int, rows: int, source: str = "rebuild") -> None:
    """写入入库标记，后续运行据此确认数据集未被改动。"""
    _RESULTS.mkdir(parents=True, exist_ok=True)
    _marker_path(dataset).write_text(
        json.dumps(
            {
                "dataset": dataset,
                "dataset_sha256": dataset_sha256(dataset),
                "documents": documents,
                "rows": rows,
                "database": _EVAL_DB,
                "collection": collection_for(dataset),
                "source": source,
                "ingested_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _quote(value: str) -> str:
    """Milvus 表达式字符串字面量转义。"""
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _base_row(pair: dict[str, Any], doc_id: str) -> dict[str, Any]:
    """构造一条子块的公共元数据。"""
    return {
        "doc_id": doc_id,
        "scope": "eval",
        "owner_id": "eval",
        "visibility": "private",
        "city": pair.get("city") or "",
        "title": pair.get("title") or "",
        "source": "retrieval_eval",
        "source_type": "eval",
        "content_hash": "",
    }


def _single_row(pair: dict[str, Any]) -> dict[str, Any]:
    """普通文档：整段作为一个子块。"""
    doc_id = f"eval:{pair['id']}"
    title = pair.get("title") or ""
    content = (pair.get("text") or "")[:_MAX_TEXT_CHARS]
    return {
        "id": doc_id,
        "parent_id": f"{doc_id}:p0",
        "parent_index": 0,
        "chunk_index": 0,
        **_base_row(pair, doc_id),
        "section": title,
        "block_type": "paragraph",
        "content": content,
        "text": f"{title} {content}"[: _MAX_TEXT_CHARS],
    }


def _rows_for_pair(pair: dict[str, Any]) -> list[dict[str, Any]]:
    """把一条评测数据转成一行或多行子块；长文档走父子块切分。"""
    text = pair.get("text") or ""
    should_split = bool(pair.get("split")) or len(text) > _LONG_DOC_THRESHOLD
    if not should_split:
        return [_single_row(pair)]

    doc_id = f"eval:{pair['id']}"
    title = pair.get("title") or ""
    try:
        _, children = chunk_parent_child(text, "txt", title=title)
    except Exception as exc:
        logger.warning("长文档切分失败，退回单块", pair=pair.get("id"), error=str(exc))
        return [_single_row(pair)]
    if not children:
        return [_single_row(pair)]

    rows: list[dict[str, Any]] = []
    for child in children:
        rows.append(
            {
                "id": f"{doc_id}:c{child.index}",
                "parent_id": f"{doc_id}:p{child.parent_index}",
                "parent_index": child.parent_index,
                "chunk_index": child.index,
                **_base_row(pair, doc_id),
                "section": child.section[:512],
                "block_type": child.block_type,
                "content": child.content[:_MAX_TEXT_CHARS],
                "text": child.text[:_MAX_TEXT_CHARS],
            }
        )
    return rows


def _all_rows(pairs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """展开所有评测数据为 Milvus 子块行。"""
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        rows.extend(_rows_for_pair(pair))
    return rows


async def collection_ready(dataset: str, expected_docs: int) -> bool:
    """判断评测集合是否已按当前数据集完成入库。"""
    configure_eval_target(dataset)
    try:
        client = get_milvus_client()
        collection = collection_for(dataset)
        if not client.has_collection(collection):
            return False
        count = await acount("")
        if count < expected_docs:
            return False
        marker = _read_marker(dataset)
        current = dataset_sha256(dataset)
        if not marker:
            # 兼容已有集合：补写入库标记，不重复入库
            _write_marker(dataset, expected_docs, count, source="backfilled")
        elif marker.get("dataset_sha256") != current:
            logger.warning(
                "评测数据集哈希与入库记录不一致，将重建评测集合",
                dataset=dataset,
                stored=marker.get("dataset_sha256"),
                current=current,
            )
            return False
        return True
    except Exception as exc:
        logger.warning("检查评测集合失败", dataset=dataset, error=str(exc))
        return False


async def rebuild_collection(dataset: str, pairs: Sequence[dict[str, Any]]) -> int:
    """重建评测集合并写入全部文档；返回写入的子块行数。"""
    configure_eval_target(dataset)
    if not init_milvus(recreate=True):
        raise RuntimeError(
            f"Milvus 评测集合初始化失败（{_EVAL_DB}/{collection_for(dataset)}），"
            "请确认 Milvus 容器已启动"
        )
    rows = _all_rows(pairs)
    inserted = await ainsert_children(rows)
    _write_marker(dataset, len(pairs), inserted)
    logger.info(
        "评测集合已重建",
        dataset=dataset,
        database=_EVAL_DB,
        collection=collection_for(dataset),
        documents=len(pairs),
        rows=inserted,
    )
    return inserted


# ---------------------------------------------------------------------------
# 检索与指标
# ---------------------------------------------------------------------------


def _filter_expr(pair: dict[str, Any]) -> str:
    """按评测配置下推城市过滤；base 数据集默认不过滤以保持基线可比。"""
    if pair.get("filter") != "city":
        return ""
    city = (pair.get("city") or "").strip()
    return f"city == {_quote(city)}" if city else ""


async def _ranked_ids(
    mode: str, query: str, top_k: int, expr: str
) -> list[str]:
    """按检索模式返回排好序、按 doc_id 去重的列表。"""
    if mode == "dense":
        vector = await asyncio.to_thread(_embed_query_sync, query)
        hits = await asyncio.to_thread(_search_dense_sync, vector, expr, top_k)
        raw = [str((hit.get("entity") or {}).get("doc_id") or "") for hit in hits]
    elif mode == "sparse":
        hits = await asyncio.to_thread(_search_sparse_sync, query, expr, top_k)
        raw = [str((hit.get("entity") or {}).get("doc_id") or "") for hit in hits]
    else:
        hits = await ahybrid_search(query, expr=expr, limit=top_k)
        raw = [hit.doc_id for hit in hits]

    ranked: list[str] = []
    seen: set[str] = set()
    for doc_id in raw:
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            ranked.append(doc_id)
    return ranked


def _ndcg(ranked: Sequence[str], relevant: set[str], top_k: int) -> float:
    """二值相关性 nDCG@k。"""
    if not relevant:
        return 0.0
    dcg = sum(
        1.0 / math.log2(index + 2)
        for index, doc_id in enumerate(ranked[:top_k])
        if doc_id in relevant
    )
    ideal = sum(
        1.0 / math.log2(index + 2)
        for index in range(min(len(relevant), top_k))
    )
    return dcg / ideal if ideal else 0.0


def _relevant_ids(pair: dict[str, Any]) -> set[str]:
    """评测数据声明的相关文档；缺省为目标文档本身。"""
    declared = pair.get("relevant") or []
    if declared:
        return {str(item) for item in declared}
    return {f"eval:{pair['id']}"}


def _per_query_metrics(
    ranked: Sequence[str], relevant: set[str], top_k: int
) -> dict[str, Any]:
    """计算单条 query 的名次、Recall、MRR 与 nDCG。"""
    first_rank: Optional[int] = None
    for index, doc_id in enumerate(ranked[:top_k]):
        if doc_id in relevant:
            first_rank = index + 1
            break

    def _recall(cutoff: int) -> float:
        hits = len(set(ranked[:cutoff]) & relevant)
        return hits / len(relevant) if relevant else 0.0

    return {
        "rank": first_rank,
        "recall@1": _recall(1),
        "recall@5": _recall(5),
        f"mrr@{top_k}": 1.0 / first_rank if first_rank else 0.0,
        f"ndcg@{top_k}": _ndcg(ranked, relevant, top_k),
    }


def _percentile(values: Sequence[float], percentile: float) -> float:
    """线性插值分位数。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * max(0.0, min(100.0, percentile)) / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _aggregate(details: Sequence[dict[str, Any]], top_k: int) -> dict[str, Any]:
    """汇总一组 query 的指标与延迟。"""
    total = max(len(details), 1)
    metrics: dict[str, Any] = {
        "recall@1": round(sum(d["recall@1"] for d in details) / total, 4),
        "recall@5": round(sum(d["recall@5"] for d in details) / total, 4),
        f"mrr@{top_k}": round(sum(d[f"mrr@{top_k}"] for d in details) / total, 4),
        f"ndcg@{top_k}": round(sum(d[f"ndcg@{top_k}"] for d in details) / total, 4),
        "hit_count": sum(1 for d in details if d.get("rank")),
        "total": len(details),
    }
    latencies = [d["latency_ms"] for d in details]
    metrics["latency_ms"] = {
        "mean": round(sum(latencies) / max(len(latencies), 1), 2),
        "p50": round(_percentile(latencies, 50), 2),
        "p95": round(_percentile(latencies, 95), 2),
    }
    return metrics


def _by_type(details: Sequence[dict[str, Any]], top_k: int) -> dict[str, Any]:
    """按数据类型（base / 难负例 / 长文档 / 模糊 query）分组汇总。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for detail in details:
        grouped.setdefault(detail.get("type") or "base", []).append(detail)
    return {
        name: {"count": len(rows), **_aggregate(rows, top_k)}
        for name, rows in sorted(grouped.items())
    }


def _usage_for_mode(
    mode: str, query_chars: int, query_count: int, top_k: int, rerank: bool
) -> dict[str, Any]:
    """估算一次检索模式的调用量与成本（不包含入库）。"""
    embedding_calls = query_count if mode in ("dense", "hybrid") else 0
    rerank_calls = query_count if mode == "hybrid" and rerank else 0
    rerank_documents = 0
    if rerank_calls:
        rerank_documents = min(
            settings.milvus.rerank_max_candidates,
            settings.milvus.dense_candidates + settings.milvus.sparse_candidates,
        ) * rerank_calls
    usage = {
        "embedding_calls": embedding_calls,
        "embedding_tokens": query_chars if mode in ("dense", "hybrid") else 0,
        "rerank_calls": rerank_calls,
        "rerank_documents": rerank_documents,
        "hyde_calls": 0,
        "hyde_input_tokens": 0,
        "hyde_output_tokens": 0,
    }
    usage["estimated_cost_cny"] = _estimate_cost(usage)
    return usage


def _estimate_cost(usage: dict[str, Any]) -> float:
    """按配置单价估算成本（CNY）；单价默认 0 时结果为 0。"""
    prices = settings.evaluation
    total = (
        usage.get("embedding_tokens", 0) / 1000.0 * prices.price_embedding_per_1k
        + usage.get("rerank_documents", 0) / 1000.0 * prices.price_rerank_per_1k
        + usage.get("hyde_input_tokens", 0) / 1000.0 * prices.price_llm_input_per_1k
        + usage.get("hyde_output_tokens", 0) / 1000.0 * prices.price_llm_output_per_1k
    )
    return round(total, 6)


def _price_note() -> dict[str, float]:
    """把当前单价写进报告，便于复现成本口径。"""
    prices = settings.evaluation
    return {
        "embedding_per_1k": prices.price_embedding_per_1k,
        "rerank_per_1k": prices.price_rerank_per_1k,
        "llm_input_per_1k": prices.price_llm_input_per_1k,
        "llm_output_per_1k": prices.price_llm_output_per_1k,
    }


async def _run_mode(
    mode: str,
    pairs: Sequence[dict[str, Any]],
    top_k: int,
    *,
    hyde_queries: Optional[dict[str, dict[str, Any]]] = None,
    rerank: bool = True,
) -> dict[str, Any]:
    """在指定模式下逐条检索，返回指标、明细与调用量。"""
    details: list[dict[str, Any]] = []
    query_chars = 0
    started = time.perf_counter()

    for pair in pairs:
        if hyde_queries is not None:
            query = hyde_queries[pair["id"]]["answer"]
        else:
            query = pair["query"]
        query_chars += len(query)
        expr = _filter_expr(pair)
        query_started = time.perf_counter()
        try:
            ranked = await _ranked_ids(mode, query, top_k, expr)
        except Exception as exc:
            logger.warning("检索失败", mode=mode, pair=pair["id"], error=str(exc))
            ranked = []
        latency_ms = round((time.perf_counter() - query_started) * 1000, 2)
        relevant = _relevant_ids(pair)
        metrics = _per_query_metrics(ranked, relevant, top_k)
        details.append(
            {
                "id": pair["id"],
                "type": pair.get("type") or "base",
                "query": pair["query"],
                "rank": metrics["rank"],
                "recall@1": metrics["recall@1"],
                "recall@5": metrics["recall@5"],
                f"mrr@{top_k}": metrics[f"mrr@{top_k}"],
                f"ndcg@{top_k}": metrics[f"ndcg@{top_k}"],
                "latency_ms": latency_ms,
            }
        )

    usage = _usage_for_mode(mode, query_chars, len(pairs), top_k, rerank)
    return {
        "mode": mode,
        "hyde": hyde_queries is not None,
        "metrics": _aggregate(details, top_k),
        "by_type": _by_type(details, top_k),
        "latency_seconds": round(time.perf_counter() - started, 2),
        "usage": usage,
        "details": details,
    }


async def _build_hyde_queries(
    pairs: Sequence[dict[str, Any]], concurrency: int
) -> dict[str, dict[str, Any]]:
    """为每条 query 生成 HyDE 假设答案；失败回退原问句。"""
    llm = get_fast_llm()
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(pair: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            started = time.perf_counter()
            try:
                result = await llm.ainvoke(
                    [
                        SystemMessage(content=RAG_HYDE_SYSTEM),
                        HumanMessage(content=build_rag_hyde_user(pair["query"])),
                    ]
                )
                content = (
                    result.content if hasattr(result, "content") else str(result)
                )
                answer = (content if isinstance(content, str) else str(content)).strip()
                usage = getattr(result, "usage_metadata", None) or {}
                input_tokens = int(
                    usage.get("input_tokens") or estimate_tokens(pair["query"])
                )
                output_tokens = int(
                    usage.get("output_tokens") or estimate_tokens(answer)
                )
                return {
                    "answer": answer or pair["query"],
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "ok": bool(answer),
                }
            except Exception as exc:
                logger.warning(
                    "HyDE 生成失败，回退原问句", pair=pair["id"], error=str(exc)
                )
                return {
                    "answer": pair["query"],
                    "input_tokens": estimate_tokens(pair["query"]),
                    "output_tokens": 0,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "ok": False,
                    "error": str(exc),
                }

    results = await asyncio.gather(*(_one(pair) for pair in pairs))
    return {pair["id"]: result for pair, result in zip(pairs, results)}


async def _city_filter_check(
    pairs: Sequence[dict[str, Any]], top_k: int
) -> dict[str, Any]:
    """跨城同名景点：对比「不过滤」时错误城市文档是否压过目标文档。"""
    targets = [pair for pair in pairs if pair.get("counterpart")]
    if not targets:
        return {}
    wrong = 0
    target_hits = 0
    details: list[dict[str, Any]] = []
    for pair in targets:
        target = f"eval:{pair['id']}"
        counterpart = f"eval:{pair['counterpart']}"
        try:
            ranked = await _ranked_ids("hybrid", pair["query"], top_k, "")
        except Exception as exc:
            logger.warning("跨城过滤校验失败", pair=pair["id"], error=str(exc))
            ranked = []
        target_rank = ranked.index(target) + 1 if target in ranked else None
        counterpart_rank = (
            ranked.index(counterpart) + 1 if counterpart in ranked else None
        )
        is_wrong = counterpart_rank is not None and (
            target_rank is None or counterpart_rank < target_rank
        )
        wrong += int(is_wrong)
        target_hits += int(target_rank is not None)
        details.append(
            {
                "id": pair["id"],
                "target_rank": target_rank,
                "counterpart_rank": counterpart_rank,
                "wrong_city_outranks": is_wrong,
            }
        )
    return {
        "queries": len(targets),
        "wrong_city_outranks": wrong,
        "wrong_city_rate": round(wrong / max(len(targets), 1), 4),
        "target_hit@k": round(target_hits / max(len(targets), 1), 4),
        "details": details,
    }


async def evaluate(
    dataset: str,
    pairs: Sequence[dict[str, Any]],
    top_k: int,
    rerank: bool,
    hyde_mode: str = "off",
    ingestion: str = "skipped",
    hyde_concurrency: int = 4,
) -> dict[str, Any]:
    """依次跑稠密 / 稀疏 / 混合检索，并按需做 HyDE 消融。"""
    collection = configure_eval_target(dataset)
    settings.milvus.rerank_enabled = rerank
    settings.milvus.rerank_top_n = max(top_k, settings.milvus.rerank_top_n)
    # 召回候选不能少于评测 top_k，否则指标会被截断
    settings.milvus.dense_candidates = max(top_k, settings.milvus.dense_candidates)
    settings.milvus.sparse_candidates = max(top_k, settings.milvus.sparse_candidates)

    queries = list(pairs)
    started = time.perf_counter()

    hyde_queries: Optional[dict[str, dict[str, Any]]] = None
    hyde_usage: dict[str, Any] = {}
    if hyde_mode in ("on", "both"):
        hyde_queries = await _build_hyde_queries(queries, hyde_concurrency)
        hyde_latencies = [item["latency_ms"] for item in hyde_queries.values()]
        hyde_usage = {
            "hyde_calls": len(hyde_queries),
            "hyde_input_tokens": sum(
                item["input_tokens"] for item in hyde_queries.values()
            ),
            "hyde_output_tokens": sum(
                item["output_tokens"] for item in hyde_queries.values()
            ),
            "hyde_latency_ms": {
                "mean": round(sum(hyde_latencies) / max(len(hyde_latencies), 1), 2),
                "p95": round(_percentile(hyde_latencies, 95), 2),
            },
        }

    runs: dict[str, dict[str, Any]] = {}
    if hyde_mode in ("off", "both"):
        for mode in _MODES:
            runs[mode] = await _run_mode(
                mode, queries, top_k, rerank=rerank
            )
            logger.info(
                "检索模式评测完成", mode=mode, hyde=False,
                metrics=runs[mode]["metrics"],
            )
    if hyde_mode in ("on", "both"):
        for mode in _MODES:
            key = f"{mode}_hyde"
            runs[key] = await _run_mode(
                mode,
                queries,
                top_k,
                hyde_queries=hyde_queries,
                rerank=rerank,
            )
            logger.info(
                "检索模式评测完成", mode=mode, hyde=True,
                metrics=runs[key]["metrics"],
            )

    # 向后兼容：results[mode] 始终是可用的主结果（优先非 HyDE）
    results = {
        mode: runs.get(mode) or runs[f"{mode}_hyde"]
        for mode in _MODES
        if mode in runs or f"{mode}_hyde" in runs
    }
    hyde_results = (
        {mode: runs[f"{mode}_hyde"] for mode in _MODES if f"{mode}_hyde" in runs}
        if hyde_mode in ("on", "both")
        else {}
    )
    ablation = [
        {
            "mode": run["mode"],
            "hyde": run["hyde"],
            **run["metrics"],
            "usage": run["usage"],
        }
        for run in runs.values()
    ]

    usage = {
        key: sum(run["usage"].get(key, 0) for run in runs.values())
        for key in (
            "embedding_calls",
            "embedding_tokens",
            "rerank_calls",
            "rerank_documents",
        )
    }
    usage.update(
        {
            "hyde_calls": hyde_usage.get("hyde_calls", 0),
            "hyde_input_tokens": hyde_usage.get("hyde_input_tokens", 0),
            "hyde_output_tokens": hyde_usage.get("hyde_output_tokens", 0),
            "hyde_latency_ms": hyde_usage.get("hyde_latency_ms", {}),
        }
    )
    usage["estimated_cost_cny"] = _estimate_cost(usage)
    usage["prices"] = _price_note()
    usage["note"] = "成本按配置单价估算（不含入库）；单价为 0 时仅展示调用量"

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": dataset,
        "dataset_files": [path.name for path in _dataset_files(dataset)],
        "dataset_sha256": dataset_sha256(dataset),
        "database": _EVAL_DB,
        "collection": collection,
        "queries": len(queries),
        "ingestion": ingestion,
        "top_k": top_k,
        "rerank": rerank,
        "hyde_mode": hyde_mode,
        "duration_seconds": round(time.perf_counter() - started, 1),
        "results": results,
        "hyde_results": hyde_results,
        "ablation": ablation,
        "usage": usage,
    }

    # 跨城同名景点：额外跑一次「不过滤」诊断，证明城市过滤的价值
    if dataset in ("hard", "all"):
        report["city_filter_check"] = await _city_filter_check(queries, top_k)
    return report


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def _print_report(report: dict[str, Any]) -> None:
    """在控制台打印指标与 HyDE 消融表。"""
    top_k = report["top_k"]
    print(
        f"\n向量检索评测完成：{report['dataset']} → "
        f"{report['database']}/{report['collection']}，"
        f"top_k={top_k}，rerank={report['rerank']}，HyDE={report['hyde_mode']}"
    )
    for run in report["ablation"]:
        m = run
        hyde = "HyDE" if run["hyde"] else "原问句"
        print(
            f"  - {run['mode']:6s} [{hyde:3s}] "
            f"Recall@1={m['recall@1']:.1%} Recall@5={m['recall@5']:.1%} "
            f"MRR={m[f'mrr@{top_k}']:.3f} nDCG@{top_k}={m[f'ndcg@{top_k}']:.3f} "
            f"p95={m['latency_ms']['p95']:.0f}ms"
        )
    usage = report.get("usage") or {}
    hyde_p95 = (usage.get("hyde_latency_ms") or {}).get("p95")
    print(
        f"  token≈{usage.get('embedding_tokens', 0)}，"
        f"精排文档≈{usage.get('rerank_documents', 0)}，"
        f"HyDE 调用={usage.get('hyde_calls', 0)}"
        f"（P95≈{hyde_p95 or 0}ms），"
        f"估算成本={usage.get('estimated_cost_cny', 0)} CNY"
    )


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="向量检索评测")
    parser.add_argument(
        "--dataset",
        choices=_DATASET_NAMES,
        default="base",
        help="评测数据集：base / hard / all",
    )
    parser.add_argument("--top-k", type=int, default=10, help="每条 query 返回条数")
    parser.add_argument("--limit", type=int, default=0, help="只评测前 N 条 query")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="强制重建并重新入库（默认仅首次或数据集变更时入库）",
    )
    parser.add_argument("--no-rerank", action="store_true", help="关闭 Cross-Encoder 精排")
    parser.add_argument(
        "--hyde",
        choices=("off", "on", "both"),
        default="off",
        help="HyDE：off=不生成；on=只跑 HyDE；both=生成消融表",
    )
    parser.add_argument(
        "--hyde-concurrency",
        type=int,
        default=settings.evaluation.hyde_concurrency,
        help="HyDE 生成并发数",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="报告输出路径；留空写到 results/retrieval_eval_<时间>.json",
    )
    args = parser.parse_args()

    setup_logging()
    # 入库始终使用完整数据集，--limit 只限制本轮评测的 query
    all_pairs = load_pairs(args.dataset)
    queries = load_pairs(args.dataset, args.limit)
    logger.info(
        "评测数据集已固定",
        dataset=args.dataset,
        sha256=dataset_sha256(args.dataset),
        queries=len(queries),
        documents=len(all_pairs),
    )
    try:
        rebuilt = args.rebuild or not asyncio.run(
            collection_ready(args.dataset, len(all_pairs))
        )
        if rebuilt:
            logger.info("重建评测集合", dataset=args.dataset, documents=len(all_pairs))
            asyncio.run(rebuild_collection(args.dataset, all_pairs))
        else:
            logger.info(
                "评测集合已入库，跳过写入，仅执行检索评测",
                dataset=args.dataset,
                documents=len(all_pairs),
            )
        report = asyncio.run(
            evaluate(
                args.dataset,
                queries,
                args.top_k,
                not args.no_rerank,
                args.hyde,
                "rebuilt" if rebuilt else "skipped",
                args.hyde_concurrency,
            )
        )
    except RuntimeError as exc:
        raise SystemExit(f"检索评测中止：{exc}")

    output = Path(args.output) if args.output else (
        _RESULTS / f"retrieval_eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_report(report)
    print(f"报告已保存: {output}")


if __name__ == "__main__":
    main()
