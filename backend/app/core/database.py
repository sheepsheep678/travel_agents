"""PostgreSQL 连接、ORM Base 与 LangGraph checkpointer 生命周期。

- 业务数据：SQLAlchemy async + asyncpg。
- LangGraph checkpointer：langgraph-checkpoint-postgres + psycopg 连接池。
- 二者都由 FastAPI lifespan 在启动时初始化、关闭时释放。
"""

from __future__ import annotations

import asyncio
import inspect
import sys
import threading
from typing import Any, AsyncIterator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from backend.app.core.config import settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_checkpointer_pool: Any = None
_checkpointer: Any = None
_checkpointer_loop: Optional[asyncio.AbstractEventLoop] = None
_checkpointer_thread: Optional[threading.Thread] = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("数据库尚未初始化，请先在 lifespan 中调用 init_database()")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("数据库尚未初始化，请先在 lifespan 中调用 init_database()")
    return _session_factory


async def init_database() -> None:
    """创建连接池、建表（create_all）并初始化 checkpointer。"""
    global _engine, _session_factory

    # 导入所有 ORM 模型，确保 Base.metadata 在建表前完整
    from backend.app.modules.knowledge import models as _knowledge_models  # noqa: F401
    from backend.app.modules.memory import models as _memory_models  # noqa: F401
    from backend.app.modules.sessions import models as _session_models  # noqa: F401
    from backend.app.modules.trip import models as _trip_models  # noqa: F401

    _engine = create_async_engine(
        settings.database.url,
        echo=settings.database.echo,
        pool_pre_ping=True,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
    )
    _session_factory = async_sessionmaker(
        _engine,
        expire_on_commit=False,
        autoflush=False,
    )

    # 先验证连接，再建表；数据库不存在 / 角色不存在 / 密码错误时给出可读错误
    try:
        async with _engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        from sqlalchemy.engine import make_url

        url = make_url(settings.database.url)
        logger.exception(
            "PostgreSQL 连接失败",
            host=url.host,
            port=url.port,
            database=url.database,
            user=url.username,
        )
        await _engine.dispose()
        raise RuntimeError(
            "无法连接 PostgreSQL "
            f"({settings.database.host}:{settings.database.port}/"
            f"{settings.database.name}，用户 {settings.database.user})：{exc}。\n"
            "请检查仓库根目录 .env 的 POSTGRES_* 配置：\n"
            "  1) POSTGRES_USER / POSTGRES_PASSWORD 是否正确、该角色是否存在；\n"
            "  2) 数据库是否已创建（可执行 python -m backend.app.scripts.init_db）；\n"
            "  3) PostgreSQL 服务是否在运行。"
        ) from exc

    logger.info("PostgreSQL 已连接，ORM 表结构已就绪")
    await init_checkpointer()


def _build_checkpointer_pool():
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    return AsyncConnectionPool(
        conninfo=settings.database.checkpoint_url,
        open=False,
        min_size=1,
        max_size=settings.database.pool_size,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            # AsyncPostgresSaver 依赖 dict 行，不设置会报 TypeError
            "row_factory": dict_row,
        },
    )


async def _create_checkpointer(saver_cls):
    pool = _build_checkpointer_pool()
    try:
        await pool.open()
        await pool.wait(timeout=10)
        saver = saver_cls(pool)
        await saver.setup()
        return pool, saver
    except Exception:
        await pool.close()
        raise


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    finally:
        loop.close()


def _proxy_async_methods(saver: Any, loop: asyncio.AbstractEventLoop) -> None:
    """把直接做数据库 I/O 的 async 方法转发到专用 Selector 线程。

    Windows 的 Proactor 主循环用于 MCP stdio 子进程；psycopg 只能在
    SelectorEventLoop 中运行，因此 checkpointer 的 I/O 独占一个线程。
    """
    for name in (
        "aget_tuple",
        "aput",
        "aput_writes",
        "adelete_thread",
        "aget_delta_channel_history",
        "adelete_for_runs",
    ):
        attr = getattr(type(saver), name, None)
        if attr is None or not inspect.iscoroutinefunction(attr):
            continue
        original = getattr(saver, name)

        def make(original):
            async def wrapper(*args, **kwargs):
                coro = original(*args, **kwargs)
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                return await asyncio.wrap_future(future)

            return wrapper

        setattr(saver, name, make(original))


async def init_checkpointer() -> None:
    """初始化 LangGraph 的 AsyncPostgresSaver。

    - 普通平台 / Selector 主循环：直接使用 AsyncPostgresSaver。
    - Windows Proactor 主循环：psycopg 不支持 Proactor，改为在独立的
      SelectorEventLoop 线程中运行连接池与 saver，并把 async 方法代理回来。
    """
    global _checkpointer_pool, _checkpointer, _checkpointer_loop, _checkpointer_thread

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    running_loop = asyncio.get_running_loop()
    if sys.platform == "win32" and isinstance(running_loop, asyncio.ProactorEventLoop):
        loop = asyncio.SelectorEventLoop()
        thread = threading.Thread(
            target=_run_loop,
            args=(loop,),
            name="pg-checkpointer",
            daemon=True,
        )
        thread.start()
        try:
            future = asyncio.run_coroutine_threadsafe(
                _create_checkpointer(AsyncPostgresSaver), loop
            )
            pool, saver = await asyncio.wrap_future(future)
        except Exception:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
            raise

        _proxy_async_methods(saver, loop)
        _checkpointer_loop = loop
        _checkpointer_thread = thread
        _checkpointer_pool = pool
        _checkpointer = saver
        logger.info("LangGraph checkpointer 已就绪（PostgreSQL，Selector 线程）")
        return

    _checkpointer_pool, _checkpointer = await _create_checkpointer(AsyncPostgresSaver)
    logger.info("LangGraph checkpointer 已就绪（PostgreSQL）")


async def close_database() -> None:
    """关闭 checkpointer 连接池与 SQLAlchemy 引擎。"""
    global _engine
    global _session_factory
    global _checkpointer_pool
    global _checkpointer
    global _checkpointer_loop
    global _checkpointer_thread

    if _checkpointer_pool is not None:
        loop = _checkpointer_loop
        try:
            if loop is not None and loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    _checkpointer_pool.close(), loop
                )
                await asyncio.wrap_future(future)
            else:
                await _checkpointer_pool.close()
        except Exception:
            logger.exception("关闭 checkpointer 连接池失败")
        _checkpointer_pool = None
    _checkpointer = None

    if _checkpointer_loop is not None:
        loop = _checkpointer_loop
        _checkpointer_loop = None
        loop.call_soon_threadsafe(loop.stop)
        thread = _checkpointer_thread
        _checkpointer_thread = None
        if thread is not None:
            thread.join(timeout=5)

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
    logger.info("PostgreSQL 连接已关闭")


def get_checkpointer() -> Any:
    """返回 AsyncPostgresSaver；未初始化时返回 None（脚本/离线调试场景）。"""
    return _checkpointer


def is_checkpointer_ready() -> bool:
    return _checkpointer is not None


async def check_database() -> bool:
    """健康检查：执行 SELECT 1。"""
    if _engine is None:
        return False
    try:
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("数据库健康检查失败")
        return False


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个 AsyncSession。"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
