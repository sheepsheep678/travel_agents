"""对话历史读写：直接使用 LangGraph checkpointer。

- 读取：``checkpointer.aget_tuple(config)`` 取 ``channel_values.messages``。
- 删除：``checkpointer.adelete_thread(thread_id)`` 清空整条会话快照。
- ``thread_id`` 就是服务端 ``chat_sessions.id``（session_id）。

消息内容不再写入 ``chat_messages`` 表；PostgreSQL 只保存
``users`` / ``chat_sessions`` 这类“有哪些会话”的元数据。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from backend.app.core.database import get_checkpointer
from backend.app.core.logging import get_logger
from backend.app.integrations.cache import (
    cache_delete,
    cache_get_json,
    cache_set_json,
    make_key,
)
from backend.app.modules.sessions.schemas import MessageOut

logger = get_logger(__name__)


def _cache_key(session_id: str) -> str:
    """历史消息缓存键：按 session 区分，写入后主动失效。"""
    return make_key("history", session_id)


def _content_to_text(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, str) and value:
        return value
    return datetime.now(timezone.utc).isoformat()


def _config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


class ChatHistory:
    """基于 checkpointer 的会话历史读取 / 删除。"""

    @staticmethod
    async def _aget_tuple(session_id: str):
        saver = get_checkpointer()
        if saver is None:
            return None
        return await saver.aget_tuple(_config(session_id))

    async def aget_messages(self, session_id: str) -> list[MessageOut]:
        # Redis 只做读加速；命中失败时回源 checkpointer，写路径会主动失效
        cache_key = _cache_key(session_id)
        cached = await cache_get_json(cache_key)
        if isinstance(cached, list):
            try:
                return [MessageOut(**item) for item in cached]
            except Exception:
                logger.debug("历史缓存反序列化失败，回源 checkpointer", session_id=session_id)

        try:
            snapshot = await self._aget_tuple(session_id)
        except Exception:
            logger.exception("读取对话历史失败", session_id=session_id)
            return []
        if snapshot is None:
            return []

        checkpoint = getattr(snapshot, "checkpoint", {}) or {}
        raw_messages: list[BaseMessage] = (
            checkpoint.get("channel_values", {}).get("messages", []) or []
        )
        created_at = _timestamp(checkpoint.get("ts"))

        messages: list[MessageOut] = []
        for index, message in enumerate(raw_messages):
            if isinstance(message, HumanMessage):
                role = "user"
            elif isinstance(message, AIMessage):
                role = "assistant"
            else:
                # ToolMessage / SystemMessage 不展示给前端
                continue

            content = _content_to_text(message)
            if role == "assistant" and not content:
                # 只有 tool_calls、没有最终文本的中间 AI 消息
                continue

            messages.append(
                MessageOut(
                    id=str(getattr(message, "id", None) or f"{session_id}:{index}"),
                    role=role,
                    content=content,
                    created_at=created_at,
                    status="done",
                )
            )
        if messages:
            # 不缓存空结果，避免新会话首轮消息被旧的空列表遮挡
            await cache_set_json(cache_key, [m.model_dump(mode="json") for m in messages])
        return messages

    @staticmethod
    async def ainvalidate(session_id: str) -> None:
        """消息写入 checkpointer 后失效历史缓存，保证下次读取拿到新消息。"""
        await cache_delete(_cache_key(session_id))

    async def aclear(self, session_id: str) -> None:
        """删除整条会话的 checkpointer 快照（等价于删除历史消息）。"""
        saver = get_checkpointer()
        if saver is None:
            return
        await saver.adelete_thread(session_id)
        await self.ainvalidate(session_id)
        logger.info("已删除会话 checkpointer 快照", session_id=session_id)
