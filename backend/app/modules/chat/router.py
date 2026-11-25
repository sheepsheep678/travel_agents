"""AI 对话路由（SSE）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from backend.app.core.deps import get_chat_service
from backend.app.modules.chat.schemas import (
    ChatCancelRequest,
    ChatRequest,
    ChatResumeRequest,
)
from backend.app.modules.chat.service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/stream", summary="AI 对话（SSE）")
async def stream_chat(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
):
    """流式对话：token / done / error 事件，消息快照由 checkpointer 保存。

    事件格式：
        data: {"type":"token","delta":"..."}
        data: {"type":"done","session_id":"..."}
        data: {"type":"error","message":"..."}
    """
    session, agent, config = await service.prepare(request)

    async def event_source():
        async for event in service.stream(session, agent, config):
            yield event

    return EventSourceResponse(
        event_source(),
        ping=10,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/resume", summary="断线续传对话（SSE）")
async def resume_chat(
    request: ChatResumeRequest,
    service: ChatService = Depends(get_chat_service),
):
    """按已收到字符数补发 token；后台生成不会因连接断开而停止。"""
    await service.check_session(request.user_id, request.session_id)

    async def event_source():
        async for event in service.resume(
            request.user_id, request.session_id, request.offset
        ):
            yield {"data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(
        event_source(),
        ping=10,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/cancel", summary="取消对话生成")
async def cancel_chat(
    request: ChatCancelRequest,
    service: ChatService = Depends(get_chat_service),
):
    """用户主动停止：终止后台生成任务。"""
    await service.cancel(request.user_id, request.session_id)
    return {"success": True, "message": "已取消"}
