"""用户 / 会话 / 消息的数据库操作。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.modules.sessions.models import ChatSession, User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def ensure_user(self, user_id: str) -> User:
        user = await self.db.get(User, user_id)
        if user is None:
            user = User(id=user_id)
            self.db.add(user)
        else:
            user.last_seen_at = _utcnow()
        await self.db.flush()
        return user

    async def get_session(self, session_id: str) -> Optional[ChatSession]:
        return await self.db.get(ChatSession, session_id)

    async def get_session_for_user(
        self, session_id: str, user_id: str
    ) -> Optional[ChatSession]:
        stmt = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_sessions(self, user_id: str) -> Sequence[ChatSession]:
        stmt = (
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def create_session(
        self, user_id: str, *, title: str = "", city: str = ""
    ) -> ChatSession:
        session = ChatSession(
            id=uuid4().hex,
            user_id=user_id,
            title=title[:120],
            city=city[:64],
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def touch_session(self, session: ChatSession) -> None:
        session.updated_at = _utcnow()
        await self.db.flush()

    async def update_session(
        self,
        session: ChatSession,
        *,
        title: Optional[str] = None,
        city: Optional[str] = None,
    ) -> ChatSession:
        if title is not None:
            session.title = title[:120]
        if city is not None:
            session.city = city[:64]
        session.updated_at = _utcnow()
        await self.db.flush()
        return session

    async def delete_session(self, session: ChatSession) -> None:
        await self.db.delete(session)

    async def commit(self) -> None:
        await self.db.commit()

    async def rollback(self) -> None:
        await self.db.rollback()
