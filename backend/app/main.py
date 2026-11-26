"""旅迹智绘后端入口。

启动方式（仓库根目录）：
    python -m backend.app.main
热重载：
    uvicorn backend.app.main:app --reload
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.config import settings, validate_config
from backend.app.core.database import close_database, init_database
from backend.app.core.exception_handlers import register_exception_handlers
from backend.app.core.logging import get_logger, setup_logging
from backend.app.core.metrics import (
    PROMETHEUS_AVAILABLE,
    instrument_app,
    prometheus_payload,
)
from backend.app.integrations.cache import close_cache, init_cache
from backend.app.integrations.mcp import close_mcp, init_mcp_async
from backend.app.integrations.memory_milvus import (
    init_memory_milvus,
    memory_milvus_error,
)
from backend.app.integrations.milvus import close_milvus, init_milvus, milvus_error
from backend.app.modules.admin.router import router as admin_router
from backend.app.modules.chat.router import router as chat_router
from backend.app.modules.health.router import router as health_router
from backend.app.modules.knowledge.router import router as knowledge_router
from backend.app.modules.memory.router import router as memory_router
from backend.app.modules.sessions.router import router as sessions_router
from backend.app.modules.trip.router import router as trip_router

# 显式导入 ORM 模型，确保 Base.metadata 在建表前已注册全部表
from backend.app.modules.knowledge import models as _knowledge_models  # noqa: F401
from backend.app.modules.memory import models as _memory_models  # noqa: F401
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

    # 3) Milvus：知识库集合/索引（失败不阻断启动，RAG 降级为无上下文）
    logger.info("正在初始化 Milvus 知识库 ...")
    try:
        ready = await asyncio.to_thread(init_milvus)
        if ready:
            logger.info(
                "Milvus 初始化完成",
                uri=settings.milvus.uri,
                collection=settings.milvus.collection,
            )
        else:
            logger.warning(
                "Milvus 未就绪，知识库检索将不可用",
                error=milvus_error(),
            )
    except Exception as exc:
        logger.warning("Milvus 初始化异常，知识库检索将不可用", error=str(exc))

    # 3.1) Milvus 用户长期记忆集合（失败不阻断，长期记忆降级为空）
    logger.info("正在初始化 Milvus 记忆集合 ...")
    try:
        memory_ready = await asyncio.to_thread(init_memory_milvus)
        if memory_ready:
            logger.info(
                "Milvus 记忆集合初始化完成",
                collection=settings.milvus.memory_collection,
            )
        else:
            logger.warning(
                "Milvus 记忆集合未就绪，长期记忆将不可用",
                error=memory_milvus_error(),
            )
    except Exception as exc:
        logger.warning("Milvus 记忆集合初始化异常，长期记忆将不可用", error=str(exc))

    # 4) Redis 缓存：工具结果 / 对话回复 / 检索结果（失败不阻断，缓存降级为直通）
    await init_cache()

    # 5) MCP：高德 / 时间 / 12306（单服务失败不影响启动）
    logger.info("正在初始化 MCP 服务 ...")
    await init_mcp_async()
    logger.info("MCP 服务初始化完成")

    try:
        yield
    finally:
        await close_mcp()
        await close_cache()
        close_milvus()
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
    instrument_app(app)

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(sessions_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(knowledge_router, prefix="/api/v1")
    app.include_router(memory_router, prefix="/api/v1")
    app.include_router(trip_router, prefix="/api/v1")

    @app.get(settings.metrics.path or "/metrics", include_in_schema=False)
    async def prometheus_metrics():
        """Prometheus 抓取端点；未启用或未安装 prometheus_client 时返回 503。"""
        payload = prometheus_payload()
        if payload is None:
            reason = (
                "prometheus_client 未安装"
                if not PROMETHEUS_AVAILABLE
                else "METRICS_ENABLED=false"
            )
            return Response(content=reason, media_type="text/plain", status_code=503)
        body, content_type = payload
        return Response(content=body, media_type=content_type)

    @app.get("/", tags=["system"], summary="服务信息")
    async def root():
        return {
            "app": settings.app.name,
            "version": settings.app.version,
            "docs": "/docs",
            "api_prefix": "/api/v1",
            "metrics": settings.metrics.path if settings.metrics.enabled else None,
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
