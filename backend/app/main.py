"""旅迹智绘后端入口。

启动方式（仓库根目录）：
    python -m backend.app.main
热重载：
    uvicorn backend.app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.config import settings, validate_config
from backend.app.core.database import close_database, init_database
from backend.app.core.exception_handlers import register_exception_handlers
from backend.app.core.logging import get_logger, setup_logging
from backend.app.integrations.mcp import close_mcp, init_mcp_async
from backend.app.modules.chat.router import router as chat_router
from backend.app.modules.health.router import router as health_router
from backend.app.modules.knowledge.router import router as knowledge_router
from backend.app.modules.sessions.router import router as sessions_router
from backend.app.modules.trip.router import router as trip_router

# 显式导入 ORM 模型，确保 Base.metadata 在建表前已注册全部表
from backend.app.modules.knowledge import models as _knowledge_models  # noqa: F401
from backend.app.modules.sessions import models as _session_models  # noqa: F401
from backend.app.modules.trip import models as _trip_models  # noqa: F401

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 1) 配置 fail-fast
    validate_config()

    # 2) 数据库：连接 + create_all + checkpointer
    logger.info("正在连接 PostgreSQL ...")
    await init_database()
    logger.info("PostgreSQL 与 LangGraph checkpointer 初始化完成")

    # 3) MCP：高德 / 时间 / 12306（单服务失败不影响启动）
    logger.info("正在初始化 MCP 服务 ...")
    await init_mcp_async()
    logger.info("MCP 服务初始化完成")

    try:
        yield
    finally:
        await close_mcp()
        await close_database()
        logger.info("应用已关闭")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app.name,
        version=settings.app.version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(sessions_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(knowledge_router, prefix="/api/v1")
    app.include_router(trip_router, prefix="/api/v1")

    @app.get("/", tags=["system"], summary="服务信息")
    async def root():
        return {
            "app": settings.app.name,
            "version": settings.app.version,
            "docs": "/docs",
            "api_prefix": "/api/v1",
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    # log_config=None：让 structlog 的根 handler 接管 uvicorn 日志
    uvicorn.run(
        "backend.app.main:app",
        host=settings.server.host,
        port=settings.server.port,
        log_config=None,
        # Windows：Proactor 主循环用于 MCP stdio；checkpointer 在独立 Selector 线程
        loop="backend.app.core.runtime:proactor_loop_factory",
    )
