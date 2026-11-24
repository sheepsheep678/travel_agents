"""记忆管理路由：查看 / 删除长期记忆与会话情景记忆。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.app.core.deps import MemoryServiceDep, SessionServiceDep
from backend.app.core.exceptions import (
    BadRequestError,
    ExternalServiceError,
    NotFoundError,
)
from backend.app.modules.memory.schemas import (
    MemoryDeleteResponse,
    MemoryListResponse,
    MemoryOut,
    SessionMemoryOut,
    SessionMemoryResponse,
)
from backend.app.modules.memory.types import MemoryKind
from backend.app.modules.sessions.service import validate_id

router = APIRouter(prefix="/memory", tags=["memory"])

_KINDS = {item.value for item in MemoryKind}


@router.get(
    "/session/{session_id}",
    response_model=SessionMemoryResponse,
    summary="查看会话情景记忆",
)
async def get_session_memory(
    session_id: str,
    user_id: str,
    service: MemoryServiceDep,
    sessions: SessionServiceDep,
):
    """返回会话摘要、已确认事实与当前任务状态。"""
    await sessions.assert_session(session_id, user_id)
    row = await service.get_session_memory(session_id, user_id)
    if row is None:
        raise NotFoundError("该会话暂无记忆")
    return SessionMemoryResponse(
        memory=SessionMemoryOut(
            session_id=row.session_id,
            summary=row.summary or "",
            facts=row.facts or {},
            task_state=row.task_state or {},
            turn_count=row.turn_count,
            updated_at=row.updated_at.isoformat(),
        )
    )


@router.get("", response_model=MemoryListResponse, summary="列出用户长期记忆")
async def list_memories(
    user_id: str,
    service: MemoryServiceDep,
    city: str = "",
    kind: str = "",
    limit: int = Query(default=100, ge=1, le=500),
):
    """按用户列出跨会话记忆，可按城市 / 类别过滤。"""
    validate_id(user_id, "user_id")
    if kind and kind not in _KINDS:
        raise BadRequestError(f"kind 不合法，可选：{', '.join(sorted(_KINDS))}")
    try:
        rows = await service.list_memories(
            user_id, city=city, kind=kind, limit=limit
        )
    except Exception as exc:
        raise ExternalServiceError(f"记忆服务不可用: {exc}") from exc
    memories = [MemoryOut.from_row(row) for row in rows]
    return MemoryListResponse(memories=memories, count=len(memories))


@router.delete(
    "/{memory_id}",
    response_model=MemoryDeleteResponse,
    summary="删除单条长期记忆",
)
async def delete_memory(
    memory_id: str,
    user_id: str,
    service: MemoryServiceDep,
):
    """按 memory_id + user_id 精确删除，防止误删他人记忆。"""
    validate_id(user_id, "user_id")
    if not memory_id.strip():
        raise BadRequestError("memory_id 不能为空")
    try:
        deleted = await service.delete_memory(memory_id, user_id)
    except Exception as exc:
        raise ExternalServiceError(f"记忆服务不可用: {exc}") from exc
    if deleted == 0:
        raise NotFoundError("记忆不存在或不属于当前用户")
    return MemoryDeleteResponse(deleted=deleted, message="已删除")


@router.delete("", response_model=MemoryDeleteResponse, summary="清空用户长期记忆")
async def clear_memories(user_id: str, service: MemoryServiceDep):
    """清空一个用户的全部跨会话记忆。"""
    validate_id(user_id, "user_id")
    try:
        deleted = await service.clear_user(user_id)
    except Exception as exc:
        raise ExternalServiceError(f"记忆服务不可用: {exc}") from exc
    return MemoryDeleteResponse(deleted=deleted, message="已清空")
