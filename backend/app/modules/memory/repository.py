"""会话情景记忆的 PostgreSQL 读写。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.modules.memory.models import SessionMemory


class SessionMemoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, session_id: str, user_id: str = "") -> Optional[SessionMemory]:
        """按会话读取；传 user_id 时同时校验归属。"""
        row = await self.db.get(SessionMemory, session_id)
        if row is None:
            return None
        if user_id and row.user_id != user_id:
            return None
        return row

    async def upsert(
        self,
        session_id: str,
        user_id: str,
        *,
        summary: Optional[str] = None,
        facts: Optional[dict] = None,
        task_state: Optional[dict] = None,
        summarized_messages: Optional[int] = None,
        turn_count: Optional[int] = None,
    ) -> SessionMemory:
        """创建或更新会话记忆，只覆盖传入的字段。"""
        row = await self.db.get(SessionMemory, session_id)
        if row is not None and user_id and row.user_id != user_id:
            raise ValueError("会话记忆不属于当前用户")
        if row is None:
            row = SessionMemory(
                session_id=session_id,
                user_id=user_id,
                summary=summary or "",
                facts=facts or {},
                task_state=task_state or {},
                summarized_messages=summarized_messages or 0,
                turn_count=turn_count or 0,
            )
            self.db.add(row)
        else:
            if summary is not None:
                row.summary = summary
            if facts is not None:
                row.facts = facts
            if task_state is not None:
                row.task_state = task_state
            if summarized_messages is not None:
                row.summarized_messages = summarized_messages
            if turn_count is not None:
                row.turn_count = turn_count
        await self.db.flush()
        return row
