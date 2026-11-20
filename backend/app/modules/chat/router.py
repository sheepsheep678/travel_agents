"""AI 对话路由（SSE）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from backend.app.core.deps import get_chat_service
from backend.app.modules.chat.schemas import ChatRequest
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
