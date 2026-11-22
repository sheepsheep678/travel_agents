"""管理端语料入库（Milvus + PostgreSQL 父子块）。

用法（仓库根目录）：
    python -m backend.app.modules.knowledge.ingest_cli
    python -m backend.app.modules.knowledge.ingest_cli --force
    python -m backend.app.modules.knowledge.ingest_cli --city 青岛

流程：MinerU/pypdf/Qwen-VL 解析 → 大模型 Markdown 排版 → 结构感知父块
→ 递归子块 → 父块写 PostgreSQL → 子块写 Milvus（稠密 + BM25 稀疏）。
每个文件的 doc_id 固定为 ``admin:{城市}``，写入前先删旧父块/子块再加。
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import hashlib
import json
import os
from pathlib import Path

from backend.app.core.config import settings
from backend.app.core.database import close_database, init_database
from backend.app.core.logging import get_logger, setup_logging
from backend.app.integrations.milvus import (
    acount,
    close_milvus,
    init_milvus,
    stats,
)
from backend.app.modules.knowledge.service import KnowledgeService
from backend.app.core.database import get_session_factory

logger = get_logger(__name__)


def _file_md5(path: str) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(4096), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_ledger(path: str) -> set[str]:
    if not os.path.exists(path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).touch()
        return set()
    with open(path, "r", encoding="utf-8") as handle:
        return {line.strip() for line in handle if line.strip()}


def _save_ledger(path: str, md5: str) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(md5 + "\n")


async def _ingest_all(force: bool, city_filter: str = "") -> int:
    await init_database()
    if not init_milvus():
        raise SystemExit("Milvus 初始化失败，请确认容器已启动")

    # 集合被重建（--recreate / 容器数据清空）时，账本仍可能是满的；
    # 这时必须忽略账本做全量入库，否则会「一条都没入库」却不报错。
    if not force:
        try:
            if await acount() == 0:
                logger.warning("Milvus 集合为空，忽略账本执行全量入库")
                force = True
        except Exception as exc:
            logger.warning("读取 Milvus 集合状态失败，按空库处理: %s", exc)
            force = True

    ledger = _load_ledger(settings.rag.md5_milvus_path)
    files = [
        path
        for path in glob.glob(
            os.path.join(settings.rag.corpus_dir, "**/*"), recursive=True
        )
        if os.path.isfile(path) and path.lower().endswith((".txt", ".pdf"))
    ]
    if city_filter:
        files = [
            path
            for path in files
            if Path(path).stem == city_filter
            or city_filter in Path(path).stem
        ]
    if not files:
        logger.warning("没有找到待入库语料", corpus_dir=settings.rag.corpus_dir)
        return 0

    factory = get_session_factory()
    failed = 0
    written = 0
    for path in sorted(files):
        city = Path(path).stem
        md5 = _file_md5(path)
        if not force and md5 in ledger:
            # 账本有记录但集合里没有该文档（例如集合重建后只恢复了部分）时仍入库
            try:
                doc_filter = f"doc_id == {json.dumps(f'admin:{city}', ensure_ascii=False)}"
                present = await acount(doc_filter)
            except Exception:
                present = 0
            if present > 0:
                logger.info("跳过（账本已记录且集合存在）", file=path, city=city)
                continue
            logger.warning("账本已记录但集合缺失，重新入库", file=path, city=city)

        logger.info("开始入库", file=path, city=city)
        try:
            async with factory() as db:
                service = KnowledgeService(db)
                item = await service.ingest_admin_file(path, city=city, force=True)
            written += 1
            _save_ledger(settings.rag.md5_milvus_path, md5)
            logger.info(
                "入库完成",
                city=city,
                doc_id=item.doc_id,
                parents=item.parent_count,
                children=item.chunk_count,
            )
        except Exception as exc:
            failed += 1
            logger.exception("入库失败", file=path, city=city, error=str(exc))

    logger.info(
        "全部处理完成",
        written=written,
        failed=failed,
        milvus=stats(),
    )
    return 1 if failed else 0


async def _run(force: bool, city_filter: str) -> int:
    try:
        return await _ingest_all(force=force, city_filter=city_filter)
    finally:
        await close_database()
        close_milvus()


def main() -> None:
    parser = argparse.ArgumentParser(description="管理端语料入库（Milvus 父子块）")
    parser.add_argument("--force", action="store_true", help="忽略账本，强制重新入库")
    parser.add_argument("--city", default="", help="只处理指定城市（文件名，不含扩展名）")
    args = parser.parse_args()

    setup_logging()
    code = asyncio.run(_run(force=args.force, city_filter=args.city))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
