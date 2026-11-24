"""会话级情景记忆：摘要、已确认事实与任务状态。

长期记忆（偏好/规则/程序经验）存 Milvus ``user_memories`` 集合；
这里只保存每个会话一条滚动更新的结构化记忆。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


def _utcnow() -> datetime:
    """当前 UTC 时间。"""
    return datetime.now(timezone.utc)


class SessionMemory(Base):
    """按会话滚动的情景记忆；删除会话时由外键级联删除。"""

    __tablename__ = "session_memories"
    __table_args__ = (
        Index("ix_session_memories_user_updated", "user_id", "updated_at"),
    )

    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    facts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    task_state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # 已压缩到 messages 中的绝对下标，用于增量压缩
    summarized_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
