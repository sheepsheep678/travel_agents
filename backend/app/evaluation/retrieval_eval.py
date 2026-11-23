"""向量检索评测：100 对 query/文档入库后比较稠密、BM25、混合检索效果。

评测集合独立于知识库（默认写入 Milvus ``default`` 库的 ``retrieval_eval``
集合），不会污染 ``travel`` 库的 ``knowledge_chunks``。

默认只在首次（集合不存在或条数不足）时入库；之后每次执行只做检索评测。
评测文本固定为 ``datasets/retrieval_eval.jsonl`` 的 100 对，修改文本后需 ``--rebuild``。

用法（仓库根目录）：
    python -m backend.app.evaluation.retrieval_eval
    python -m backend.app.evaluation.retrieval_eval --no-rerank --limit 20
    python -m backend.app.evaluation.retrieval_eval --rebuild

结果保存到 ``backend/app/evaluation/results/retrieval_eval_<时间>.json``。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from backend.app.core.config import settings
from backend.app.core.logging import get_logger, setup_logging
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

logger = get_logger(__name__)

_DATASET = Path(__file__).parent / "datasets" / "retrieval_eval.jsonl"
_RESULTS = Path(__file__).parent / "results"
_MARKER = _RESULTS / "retrieval_eval_ingested.json"
_EVAL_DB = os.getenv("RETRIEVAL_EVAL_DB", "default")
_EVAL_COLLECTION = os.getenv("RETRIEVAL_EVAL_COLLECTION", "retrieval_eval")


def load_pairs(limit: int = 0) -> list[dict[str, Any]]:
    """读取 query/文档评测集。"""
    rows = [json.loads(line) for line in _DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[:limit] if limit and limit > 0 else rows


def _row(pair: dict[str, Any]) -> dict[str, Any]:
    """把一条评测数据转换成 Milvus 子块行。"""
    doc_id = f"eval:{pair['id']}"
    return {
        "id": doc_id,
        "doc_id": doc_id,
        "parent_id": f"{doc_id}:p0",
        "parent_index": 0,
        "chunk_index": 0,
        "scope": "eval",
        "owner_id": "eval",
        "visibility": "private",
        "city": pair["city"],
        "title": pair["title"],
        "source": "retrieval_eval",
        "source_type": "eval",
        "section": pair["title"],
        "block_type": "paragraph",
        "content_hash": "",
        "content": pair["text"],
        "text": f"{pair['title']} {pair['text']}",
    }


def dataset_sha256() -> str:
    """固定评测集的 SHA256，用于确认文本未被改动。"""
    return hashlib.sha256(_DATASET.read_bytes()).hexdigest()


def _read_marker() -> dict:
    """读取入库标记（记录入库时的数据集哈希与条数）。"""
    try:
        return json.loads(_MARKER.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_marker(rows: int, source: str = "rebuild") -> None:
    """写入入库标记，后续运行据此确认数据集未被改动。"""
    _RESULTS.mkdir(parents=True, exist_ok=True)
    _MARKER.write_text(
        json.dumps(
            {
                "dataset_sha256": dataset_sha256(),
                "rows": rows,
                "database": _EVAL_DB,
                "collection": _EVAL_COLLECTION,
                "source": source,
                "ingested_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def configure_eval_target() -> None:
    """把 Milvus 指向独立评测库/集合，避免误用生产知识库。"""
    settings.milvus.db_name = _EVAL_DB
    settings.milvus.collection = _EVAL_COLLECTION


async def collection_ready(expected: int) -> bool:
    """判断评测集合是否已按固定数据集完成入库。"""
    configure_eval_target()
    try:
        client = get_milvus_client()
        if not client.has_collection(_EVAL_COLLECTION):
            return False
        count = await acount("")
        if count < expected:
            return False
        marker = _read_marker()
        current = dataset_sha256()
        if not marker:
            # 兼容已有集合：补写入库标记，不重复入库
            _write_marker(count, source="backfilled")
        elif marker.get("dataset_sha256") != current:
            logger.warning(
                "评测数据集哈希与入库记录不一致，仍只执行评测；如需重灌请加 --rebuild",
                stored=marker.get("dataset_sha256"),
                current=current,
            )
        return True
    except Exception as exc:
        logger.warning("检查评测集合失败", error=str(exc))
        return False


async def rebuild_collection(pairs: Sequence[dict[str, Any]]) -> None:
    """仅在首次或显式 --rebuild 时重建集合并写入全部文档。"""
    configure_eval_target()
    if not init_milvus(recreate=True):
        raise RuntimeError(
            f"Milvus 评测集合初始化失败（{_EVAL_DB}/{_EVAL_COLLECTION}），"
            "请确认 Milvus 容器已启动"
        )
    inserted = await ainsert_children([_row(pair) for pair in pairs])
    _write_marker(inserted)
    logger.info("评测集合已重建", database=_EVAL_DB, collection=_EVAL_COLLECTION, rows=inserted)


async def _ranked_ids(mode: str, query: str, top_k: int) -> list[str]:
    """按检索模式返回排好序的 doc_id 列表。"""
    if mode == "dense":
        vector = await asyncio.to_thread(_embed_query_sync, query)
        hits = await asyncio.to_thread(_search_dense_sync, vector, "", top_k)
        return [str((hit.get("entity") or {}).get("doc_id") or "") for hit in hits]
    if mode == "sparse":
        hits = await asyncio.to_thread(_search_sparse_sync, query, "", top_k)
        return [str((hit.get("entity") or {}).get("doc_id") or "") for hit in hits]
    hits = await ahybrid_search(query, expr="", limit=top_k)
    return [hit.doc_id for hit in hits]


def _metrics(ranks: Sequence[int | None], top_k: int) -> dict[str, float]:
    """由每条 query 的目标名次计算 Recall@1/5 与 MRR。"""
    total = max(len(ranks), 1)
    recall1 = sum(1 for r in ranks if r == 1) / total
    recall5 = sum(1 for r in ranks if r is not None and r <= 5) / total
    mrr = sum(1.0 / r for r in ranks if r is not None) / total
    return {
        "recall@1": round(recall1, 4),
        "recall@5": round(recall5, 4),
        f"mrr@{top_k}": round(mrr, 4),
        "hit_count": sum(1 for r in ranks if r is not None),
        "total": len(ranks),
    }


async def evaluate(
    pairs: Sequence[dict[str, Any]],
    top_k: int,
    rerank: bool,
    ingestion: str = "skipped",
) -> dict[str, Any]:
    """依次跑稠密 / 稀疏 / 混合检索并汇总指标。"""
    configure_eval_target()
    settings.milvus.rerank_enabled = rerank
    settings.milvus.rerank_top_n = top_k
    # 召回候选不能少于评测 top_k，否则指标会被截断
    settings.milvus.dense_candidates = max(top_k, settings.milvus.dense_candidates)
    settings.milvus.sparse_candidates = max(top_k, settings.milvus.sparse_candidates)
    queries = list(pairs)
    results: dict[str, Any] = {}
    started = time.perf_counter()

    for mode in ("dense", "sparse", "hybrid"):
        ranks: list[int | None] = []
        details: list[dict[str, Any]] = []
        mode_started = time.perf_counter()
        for pair in queries:
            target = f"eval:{pair['id']}"
            try:
                ids = await _ranked_ids(mode, pair["query"], top_k)
                rank = ids.index(target) + 1 if target in ids else None
            except Exception as exc:
                logger.warning("检索失败", mode=mode, pair=pair["id"], error=str(exc))
                rank = None
            ranks.append(rank)
            details.append({"id": pair["id"], "rank": rank})
        results[mode] = {
            "metrics": _metrics(ranks, top_k),
            "latency_seconds": round(time.perf_counter() - mode_started, 2),
            "details": details,
        }
        logger.info("检索模式评测完成", mode=mode, metrics=results[mode]["metrics"])

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": _DATASET.name,
        "dataset_sha256": dataset_sha256(),
        "database": _EVAL_DB,
        "collection": _EVAL_COLLECTION,
        "queries": len(queries),
        "ingestion": ingestion,
        "top_k": top_k,
        "rerank": rerank,
        "duration_seconds": round(time.perf_counter() - started, 1),
        "results": results,
    }


def _print_report(report: dict[str, Any]) -> None:
    """在控制台打印各模式指标。"""
    print(
        f"\n向量检索评测完成：{report['database']}/{report['collection']}，"
        f"top_k={report['top_k']}，rerank={report['rerank']}"
    )
    mrr_key = f"mrr@{report['top_k']}"
    for mode, data in report["results"].items():
        m = data["metrics"]
        print(
            f"  - {mode:6s} Recall@1={m['recall@1']:.1%}  "
            f"Recall@5={m['recall@5']:.1%}  MRR={m[mrr_key]:.3f}  "
            f"({data['latency_seconds']}s)"
        )


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="向量检索评测")
    parser.add_argument("--top-k", type=int, default=10, help="每条 query 返回条数")
    parser.add_argument("--limit", type=int, default=0, help="只评测前 N 条 query")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="强制重建并重新入库（默认仅首次入库，后续只评测）",
    )
    parser.add_argument("--no-rerank", action="store_true", help="关闭 Cross-Encoder 精排")
    args = parser.parse_args()

    setup_logging()
    # 入库始终使用完整的 100 对固定数据，--limit 只限制本轮评测的 query
    all_pairs = load_pairs()
    queries = load_pairs(args.limit)
    logger.info(
        "评测数据集已固定",
        dataset=_DATASET.name,
        sha256=dataset_sha256(),
        queries=len(queries),
    )
    try:
        rebuilt = args.rebuild or not asyncio.run(collection_ready(len(all_pairs)))
        if rebuilt:
            logger.info("首次或强制入库评测集合", ingest=True, rows=len(all_pairs))
            asyncio.run(rebuild_collection(all_pairs))
        else:
            logger.info("评测集合已入库，跳过写入，仅执行检索评测", ingest=False, rows=len(all_pairs))
        report = asyncio.run(
            evaluate(
                queries,
                args.top_k,
                not args.no_rerank,
                "rebuilt" if rebuilt else "skipped",
            )
        )
    except RuntimeError as exc:
        raise SystemExit(f"检索评测中止：{exc}")
    _RESULTS.mkdir(parents=True, exist_ok=True)
    path = _RESULTS / f"retrieval_eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_report(report)
    print(f"报告已保存: {path}")


if __name__ == "__main__":
    main()
