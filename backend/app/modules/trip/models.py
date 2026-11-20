"""行程规划记录表（与 LangGraph checkpoint 的 thread_id 关联）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TripPlanRecord(Base):
    __tablename__ = "trip_plans"
    __table_args__ = (
        Index("ix_trip_plans_user_created", "user_id", "created_at"),
        Index("ix_trip_plans_thread", "thread_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True
    )
    thread_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    request: Mapped[Any] = mapped_column(JSONB, nullable=False)
    plan: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
