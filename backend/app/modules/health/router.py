"""健康检查路由。"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.core.config import settings
from backend.app.core.database import check_database, is_checkpointer_ready
from backend.app.integrations.cache import check_cache
from backend.app.integrations.mcp import get_mcp_status
from backend.app.integrations.memory_milvus import (
    check_memory_milvus,
    memory_milvus_error,
)
from backend.app.integrations.milvus import check_milvus, milvus_error

router = APIRouter(prefix="/health", tags=["system"])


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
    database: bool
    checkpointer: bool
    redis: bool = False
    milvus: bool = False
    memory_milvus: bool = False
    mcp: Dict[str, bool] = Field(default_factory=dict)
    errors: Dict[str, str] = Field(default_factory=dict)


@router.get("", response_model=HealthResponse, summary="健康检查")
async def health() -> HealthResponse:
    mcp_status: Dict[str, Any] = get_mcp_status()
    database_ok = await check_database()
    redis_ok = await check_cache()
    milvus_ok = await asyncio.to_thread(check_milvus)
    memory_milvus_ok = await asyncio.to_thread(check_memory_milvus)
    errors = dict(mcp_status.get("errors", {}))
    if settings.redis.enabled and not redis_ok:
        errors["redis"] = "Redis 不可达，缓存已降级为直通"
    if not milvus_ok and milvus_error():
        errors["milvus"] = milvus_error()
    if not memory_milvus_ok and memory_milvus_error():
        errors["memory_milvus"] = memory_milvus_error()
    return HealthResponse(
        status="ok" if database_ok else "degraded",
        app_name=settings.app.name,
        version=settings.app.version,
        database=database_ok,
        checkpointer=is_checkpointer_ready(),
        redis=redis_ok,
        milvus=milvus_ok,
        memory_milvus=memory_milvus_ok,
        mcp=mcp_status.get("ready", {}),
        errors=errors,
    )
