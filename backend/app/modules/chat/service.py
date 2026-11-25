"""AI 对话业务：会话校验、checkpointer 快照、对话工作流与 SSE token 流。

消息不再写 ``chat_messages`` 表：
- 会话元数据（哪些会话）在 PostgreSQL 的 ``chat_sessions``；
- 对话内容快照由 LangGraph checkpointer 按 ``thread_id = session_id`` 保存；
- 读取用 ``aget_state`` / ``aget_tuple``，删除用 ``adelete_thread``。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from langchain_core.messages import HumanMessage, RemoveMessage
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
from backend.app.modules.chat.history import ChatHistory
from backend.app.modules.chat.schemas import ChatRequest
from backend.app.modules.sessions.models import ChatSession
from backend.app.modules.sessions.repository import SessionRepository
from backend.app.modules.sessions.service import validate_id

logger = get_logger(__name__)


def _sse(payload: dict) -> dict:
    return {"data": json.dumps(payload, ensure_ascii=False)}


@dataclass
class ChatRun:
    """一次对话生成的实时文本缓冲，供断线重连按字符偏移补发。"""

    session_id: str
    user_id: str = ""
    text: str = ""
    done: bool = False
    cancelled: bool = False
    error: str = ""
    task: Optional[asyncio.Task] = None
    created_at: float = field(default_factory=time.time)


_CHAT_RUNS: dict[str, ChatRun] = {}
_CHAT_RUN_TTL_SECONDS = 600


def _prune_chat_runs() -> None:
    """清理已结束且超过 TTL 的对话缓冲。"""
    now = time.time()
    for key, run in list(_CHAT_RUNS.items()):
        if run.done and now - run.created_at > _CHAT_RUN_TTL_SECONDS:
            _CHAT_RUNS.pop(key, None)


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
            # 重新生成要拿到新回复，绕过 Redis 里的对话回复缓存
            config["configurable"]["skip_cache"] = True
            # 补齐记忆节点需要的归属字段（首轮重新生成时状态里可能还没有）
            await agent.aupdate_state(
                config,
                {
                    "session_id": session.id,
                    "user_id": request.user_id,
                    "city": request.city or session.city or "",
                },
            )
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
                config,
                {
                    "messages": [HumanMessage(content=content)],
                    "city": request.city or session.city or "",
                    "user_id": request.user_id,
                    "session_id": session.id,
                },
            )
            title = content.replace("\n", " ")[:18] if not session.title else None
            await self.sessions.update_session(
                session, title=title, city=(request.city or None)
            )

        await self.sessions.commit()
        # 新消息/重新生成已写入 checkpointer，历史缓存必须失效
        await ChatHistory.ainvalidate(session.id)
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
            # as_node 只决定更新归属，不影响下次从 START 重新执行
            await agent.aupdate_state(
                config, {"messages": remove}, as_node="safety"
            )

    async def check_session(self, user_id: str, session_id: str) -> ChatSession:
        """校验会话归属，供 SSE 响应开始前调用。"""
        session = await self.sessions.get_session_for_user(session_id, user_id)
        if session is None:
            raise NotFoundError("会话不存在或不属于当前用户")
        return session

    async def stream(
        self,
        session: ChatSession,
        agent: Any,
        config: dict,
    ) -> AsyncIterator[dict]:
        """首次订阅：后台生成并实时推送 token；连接断开不影响生成完成。"""
        run = self._start_run(session, agent, config)
        async for event in self._subscribe(run, 0):
            yield _sse(event)

    def _start_run(self, session: ChatSession, agent: Any, config: dict) -> ChatRun:
        """创建后台生成任务；同一会话残留的旧任务先取消。"""
        _prune_chat_runs()
        previous = _CHAT_RUNS.get(session.id)
        if previous is not None and not previous.done:
            logger.info("取消上一轮未完成的对话生成", session_id=session.id)
            previous.cancelled = True
            if previous.task is not None and not previous.task.done():
                previous.task.cancel()
        run = ChatRun(session_id=session.id, user_id=session.user_id or "")
        _CHAT_RUNS[session.id] = run
        run.task = asyncio.create_task(self._execute(session, agent, config, run))
        return run

    async def _execute(
        self,
        session: ChatSession,
        agent: Any,
        config: dict,
        run: ChatRun,
    ) -> None:
        """后台运行对话工作流，把用户可见 token 累积到缓冲区。"""
        try:
            async with asyncio.timeout(settings.chat.response_timeout):
                # 节点通过 get_stream_writer() 只推送面向用户的文本
                async for chunk in agent.astream(
                    {"messages": []},
                    config,
                    stream_mode="custom",
                ):
                    if run.cancelled:
                        break
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("type") == "token" and chunk.get("delta"):
                        run.text += chunk["delta"]
        except asyncio.CancelledError:
            requested = run.cancelled
            run.cancelled = True
            # requested=False 表示不是 /chat/cancel 或新请求替换，而是外部强制取消
            logger.info(
                "对话后台生成被取消",
                session_id=session.id,
                requested=requested,
            )
            raise
        except Exception as exc:
            kind = llm_error_kind(exc)
            run.error = format_llm_error(exc)
            if kind:
                logger.warning(
                    "对话流式生成失败（上游账户/权限问题）",
                    session_id=session.id,
                    kind=kind,
                    error=run.error,
                )
            else:
                logger.exception("对话流式生成失败", session_id=session.id)
        finally:
            # 助手消息已随节点执行写入 checkpointer，刷新历史时不能读到旧缓存
            run.done = True
            try:
                await asyncio.shield(ChatHistory.ainvalidate(session.id))
            except BaseException:
                pass

    async def _subscribe(self, run: ChatRun, offset: int) -> AsyncIterator[dict]:
        """从 offset 之后补发文本，并持续推送新 token 直到生成结束。"""
        sent = max(0, offset)
        while True:
            if len(run.text) > sent:
                yield {"type": "token", "delta": run.text[sent:]}
                sent = len(run.text)
            if run.done:
                if run.error:
                    yield {"type": "error", "message": run.error}
                else:
                    yield {"type": "done", "session_id": run.session_id}
                return
            await asyncio.sleep(0.05)

    async def resume(
        self, user_id: str, session_id: str, offset: int = 0
    ) -> AsyncIterator[dict]:
        """断线重连：校验会话后补发已生成但客户端未收到的 token。"""
        await self.check_session(user_id, session_id)
        run = _CHAT_RUNS.get(session_id)
        if run is None:
            yield {"type": "done", "session_id": session_id}
            return
        async for event in self._subscribe(run, offset):
            yield event

    async def cancel(self, user_id: str, session_id: str) -> None:
        """用户主动停止：终止后台生成，保留已生成的部分文本。"""
        await self.check_session(user_id, session_id)
        run = _CHAT_RUNS.get(session_id)
        if run is None or run.done:
            return
        logger.info("收到用户取消对话生成", session_id=session_id)
        run.cancelled = True
        if run.task is not None and not run.task.done():
            run.task.cancel()
