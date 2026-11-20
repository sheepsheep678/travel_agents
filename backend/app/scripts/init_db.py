"""初始化 PostgreSQL：数据库不存在时创建，然后建表 + 初始化 checkpointer。

用法（仓库根目录）：
    python -m backend.app.scripts.init_db

连接信息来自 .env 的 POSTGRES_HOST / POSTGRES_PORT / POSTGRES_USER /
POSTGRES_PASSWORD / POSTGRES_DB（均有默认值），该账号需要有 CREATEDB 权限。
"""

from __future__ import annotations

import asyncio

import asyncpg

from backend.app.core.config import settings
from backend.app.core.database import close_database, init_database
from backend.app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


async def ensure_database() -> None:
    db = settings.database
    database = db.name
    if not database:
        raise RuntimeError("POSTGRES_DB 不能为空")

    try:
        conn = await asyncpg.connect(
            host=db.host,
            port=db.port,
            user=db.user,
            password=db.password or None,
            database="postgres",
        )
    except Exception as exc:
        raise RuntimeError(
            "无法连接 PostgreSQL "
            f"({db.host}:{db.port}，用户 {db.user})：{exc}。\n"
            "请确认 POSTGRES_USER / POSTGRES_PASSWORD 正确，且该角色已存在；"
            "可以用超级用户 postgres 创建角色：\n"
            "  CREATE ROLE <用户名> LOGIN PASSWORD '<密码>' CREATEDB;"
        ) from exc
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", database
        )
        if exists:
            logger.info("数据库已存在", database=database)
            return
        # 数据库名来自本地配置，加引号防止大小写/特殊字符问题
        await conn.execute(f'CREATE DATABASE "{database}"')
        logger.info("数据库已创建", database=database)
    finally:
        await conn.close()


async def main() -> None:
    setup_logging()
    await ensure_database()
    await init_database()
    await close_database()
    logger.info("数据库初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
