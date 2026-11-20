"""行程规划记录的数据库操作。"""

from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.modules.trip.models import TripPlanRecord


class TripRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        *,
        user_id: Optional[str],
        session_id: Optional[str],
        thread_id: str,
        request: dict[str, Any],
    ) -> TripPlanRecord:
        record = TripPlanRecord(
            id=uuid4().hex,
            user_id=user_id or None,
            session_id=session_id or None,
            thread_id=thread_id,
            status="running",
            request=request,
        )
        self.db.add(record)
        await self.db.flush()
        return record

    async def update_status(
        self,
        record: TripPlanRecord,
        *,
        status: str,
        plan: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        record.status = status
        if plan is not None:
            record.plan = plan
        if error is not None:
            record.error = error[:4000]
        await self.db.flush()

    async def get(self, record_id: str) -> Optional[TripPlanRecord]:
        return await self.db.get(TripPlanRecord, record_id)

    async def commit(self) -> None:
        await self.db.commit()

    async def rollback(self) -> None:
        await self.db.rollback()
