"""AI 对话业务：会话校验、checkpointer 快照、LangChain Agent 与 SSE token 流。

消息不再写 ``chat_messages`` 表：
- 会话元数据（哪些会话）在 PostgreSQL 的 ``chat_sessions``；
- 对话内容快照由 LangGraph checkpointer 按 ``thread_id = session_id`` 保存；
- 读取用 ``aget_state`` / ``aget_tuple``，删除用 ``adelete_thread``。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    RemoveMessage,
)
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.database import get_checkpointer
from backend.app.core.exceptions import (
    BadRequestError,
    ConfigurationError,
    NotFoundError,
)
from backend.app.core.llm_errors import format_llm_error, llm_error_kind
from backend.app.core.logging import get_logger
from backend.app.modules.chat.agent import chat_config, get_chat_agent
from backend.app.modules.chat.schemas import ChatRequest
from backend.app.modules.sessions.models import ChatSession
from backend.app.modules.sessions.repository import SessionRepository
from backend.app.modules.sessions.service import validate_id

logger = get_logger(__name__)


def _chunk_text(chunk: Any) -> str:
    content = getattr(chunk, "content", "")
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


def _sse(payload: dict) -> dict:
    return {"data": json.dumps(payload, ensure_ascii=False)}


class ChatService:
    def __init__(self, db: AsyncSession) -> None:
        self.sessions = SessionRepository(db)

    async def prepare(self, request: ChatRequest) -> tuple[ChatSession, Any, dict]:
        """校验会话、更新元数据，并把本轮用户消息写入 checkpointer。"""
        validate_id(request.user_id, "user_id")
        validate_id(request.session_id, "session_id")

        session = await self.sessions.get_session_for_user(
            request.session_id, request.user_id
        )
        if session is None:
            raise NotFoundError("会话不存在或不属于当前用户")
        if get_checkpointer() is None:
            raise ConfigurationError(
                "对话需要 PostgreSQL checkpointer，请确认数据库已启动并执行过 init_db"
            )

        agent = get_chat_agent(request.city or session.city, request.user_id)
        config = chat_config(session.id)

        if request.regenerate:
            await self._remove_last_answer(agent, config)
            await self.sessions.update_session(
                session, city=(request.city or None)
            )
        else:
            content = (request.message or "").strip()
            if not content:
                raise BadRequestError("消息不能为空")
            # 先落 checkpointer：即使客户端随后断开，用户消息也不会丢
            await agent.aupdate_state(
                config, {"messages": [HumanMessage(content=content)]}
            )
            title = content.replace("\n", " ")[:18] if not session.title else None
            await self.sessions.update_session(
                session, title=title, city=(request.city or None)
            )

        await self.sessions.commit()
        return session, agent, config

    @staticmethod
    async def _remove_last_answer(agent: Any, config: dict) -> None:
        """重新生成：删除最后一条用户消息之后的整个助手轮次。

        必须连同 AI tool_calls 消息、ToolMessage 和最终 AI 回复一起删除，
        只删最后一条 AI 会让 Agent 的 branch 路由拿到不一致的 messages。
        """
        state = await agent.aget_state(config)
        messages = list((state.values or {}).get("messages", []) or [])
        if not messages:
            return

        last_human_index = None
        for index in range(len(messages) - 1, -1, -1):
            if isinstance(messages[index], HumanMessage):
                last_human_index = index
                break
        if last_human_index is None:
            return

        remove = [
            RemoveMessage(id=message.id)
            for message in messages[last_human_index + 1:]
            if getattr(message, "id", None)
        ]
        if remove:
            await agent.aupdate_state(
                config, {"messages": remove}, as_node="model"
            )

    async def stream(
        self,
        session: ChatSession,
        agent: Any,
        config: dict,
    ) -> AsyncIterator[dict]:
        """运行 Agent，把文本 token 以 SSE 推给前端；快照由 checkpointer 自动保存。"""
        try:
            async with asyncio.timeout(settings.chat.response_timeout):
                async for chunk, _metadata in agent.astream(
                    {"messages": []},
                    config,
                    stream_mode="messages",
                ):
                    # 只转发模型文本；ToolMessage / tool_call 参数块没有文本内容
                    if not isinstance(chunk, (AIMessage, AIMessageChunk)):
                        continue
                    text = _chunk_text(chunk)
                    if not text:
                        continue
                    yield _sse({"type": "token", "delta": text})

            yield _sse({"type": "done", "session_id": session.id})
        except asyncio.CancelledError:
            # 用户消息在 prepare 中已写入 checkpointer；
            # 未完成的助手节点不会产生半截快照，直接结束即可。
            logger.info("对话流被取消", session_id=session.id)
            raise
        except Exception as exc:
            kind = llm_error_kind(exc)
            message = format_llm_error(exc)
            if kind:
                # 欠费/未开通/Key 失效属于上游账户问题，不打完整堆栈
                logger.warning(
                    "对话流式生成失败（上游账户/权限问题）",
                    session_id=session.id,
                    kind=kind,
                    error=message,
                )
            else:
                logger.exception("对话流式生成失败", session_id=session.id)
            yield _sse({"type": "error", "message": message})
