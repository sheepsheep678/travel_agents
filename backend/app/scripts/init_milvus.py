"""初始化 Milvus：数据库 / 集合 / BM25 函数 / 稠密+稀疏+标量索引。

用法（仓库根目录）：
    python -m backend.app.scripts.init_milvus
    python -m backend.app.scripts.init_milvus --recreate   # 删除集合并重建

注意：集合 schema 创建后不可修改；修改字段、维度或度量必须 --recreate。
"""

from __future__ import annotations

import argparse
import json

from backend.app.core.config import settings
from backend.app.core.logging import get_logger, setup_logging
from backend.app.integrations.memory_milvus import init_memory_milvus, memory_stats
from backend.app.integrations.milvus import close_milvus, init_milvus, stats

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化 Milvus 知识库集合")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="删除已存在的集合并按当前 schema 重建（会丢失全部子块）",
    )
    args = parser.parse_args()

    setup_logging()
    ready = init_milvus(recreate=args.recreate)
    if not ready:
        raise SystemExit("Milvus 初始化失败，请确认容器已启动且 MILVUS_URI 正确")

    memory_ready = init_memory_milvus(recreate=args.recreate)
    if not memory_ready:
        logger.warning("Milvus 记忆集合初始化失败，长期记忆将不可用")

    print(
        json.dumps(
            {
                "uri": settings.milvus.uri,
                "database": settings.milvus.db_name,
                "collection": settings.milvus.collection,
                "dense_dim": settings.milvus.dense_dim,
                "dense_metric": settings.milvus.dense_metric,
                "sparse_metric": settings.milvus.sparse_metric,
                "analyzer": settings.milvus.analyzer_tokenizer,
                "stats": stats(),
                "memory": memory_stats(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    close_milvus()
    logger.info("Milvus 初始化完成")


if __name__ == "__main__":
    main()
