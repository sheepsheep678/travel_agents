"""会话业务：用户注册、会话创建 / 校验 / 列表 / 删除。"""

from __future__ import annotations

import re
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.exceptions import (
    BadRequestError,
    ExternalServiceError,
    NotFoundError,
    PermissionDeniedError,
)
from backend.app.modules.chat.history import ChatHistory
from backend.app.modules.sessions.models import ChatSession
from backend.app.modules.sessions.repository import SessionRepository
from backend.app.modules.sessions.schemas import MessageOut, SessionOut

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def validate_id(value: str, field: str) -> str:
    if not _ID_RE.match(value or ""):
        raise BadRequestError(f"{field} 格式不合法（8-64 位字母、数字、下划线或短横线）")
    return value


def _session_out(
    session: ChatSession, messages: Sequence[MessageOut] = ()
) -> SessionOut:
    return SessionOut(
        id=session.id,
        user_id=session.user_id,
        title=session.title,
        city=session.city,
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
        messages=list(messages),
    )


class SessionService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = SessionRepository(db)
        self.history = ChatHistory()

    async def ensure_user(self, user_id: str) -> str:
        validate_id(user_id, "user_id")
        await self.repo.ensure_user(user_id)
        await self.repo.commit()
        return user_id

    async def ensure_session(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        *,
        title: str = "",
        city: str = "",
    ) -> SessionOut:
        """校验 user_id + session_id；不存在则新建一个会话返回。"""
        validate_id(user_id, "user_id")
        await self.repo.ensure_user(user_id)

        session: Optional[ChatSession] = None
        if session_id:
            validate_id(session_id, "session_id")
            existing = await self.repo.get_session(session_id)
            if existing is not None:
                if existing.user_id != user_id:
                    raise PermissionDeniedError("会话不属于当前用户")
                session = existing
            else:
                session = await self.repo.create_session(user_id, title=title, city=city)
        else:
            session = await self.repo.create_session(user_id, title=title, city=city)

        messages = await self.history.aget_messages(session.id)
        await self.repo.touch_session(session)
        await self.repo.commit()
        return _session_out(session, messages)

    async def create_session(
        self, user_id: str, *, title: str = "", city: str = ""
    ) -> SessionOut:
        validate_id(user_id, "user_id")
        await self.repo.ensure_user(user_id)
        session = await self.repo.create_session(user_id, title=title, city=city)
        await self.repo.commit()
        return _session_out(session)

    async def list_sessions(self, user_id: str) -> list[SessionOut]:
        validate_id(user_id, "user_id")
        sessions = await self.repo.list_sessions(user_id)
        return [_session_out(session) for session in sessions]

    async def get_session(self, session_id: str, user_id: str) -> SessionOut:
        validate_id(user_id, "user_id")
        session = await self.repo.get_session_for_user(session_id, user_id)
        if session is None:
            raise NotFoundError("会话不存在")
        messages = await self.history.aget_messages(session.id)
        return _session_out(session, messages)

    async def delete_session(self, session_id: str, user_id: str) -> None:
        validate_id(user_id, "user_id")
        session = await self.repo.get_session_for_user(session_id, user_id)
        if session is None:
            raise NotFoundError("会话不存在")
        # 先删 checkpointer 快照，再删会话元数据；失败时保留会话便于重试
        try:
            await self.history.aclear(session.id)
        except Exception as exc:
            raise ExternalServiceError(f"删除会话历史失败: {exc}") from exc
        await self.repo.delete_session(session)
        await self.repo.commit()

    async def update_session(
        self,
        session_id: str,
        user_id: str,
        *,
        title: Optional[str] = None,
        city: Optional[str] = None,
    ) -> SessionOut:
        validate_id(user_id, "user_id")
        session = await self.repo.get_session_for_user(session_id, user_id)
        if session is None:
            raise NotFoundError("会话不存在")
        await self.repo.update_session(session, title=title, city=city)
        await self.repo.commit()
        return _session_out(session)

    async def assert_session(self, session_id: str, user_id: str) -> ChatSession:
        """供行程 / 对话模块校验会话归属。"""
        validate_id(user_id, "user_id")
        validate_id(session_id, "session_id")
        session = await self.repo.get_session_for_user(session_id, user_id)
        if session is None:
            raise NotFoundError("会话不存在或不属于当前用户")
        return session
