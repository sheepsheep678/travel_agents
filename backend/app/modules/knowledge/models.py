"""知识库文档元数据表。

向量仍存放在 Chroma（``data/chroma_db``）；PostgreSQL 只保存文档级元数据，
用于列表、去重与按 owner 删除，避免每次列表都全量扫描向量库。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("owner_id", "scope", "content_hash", name="uq_knowledge_owner_hash"),
        Index("ix_knowledge_owner_scope", "owner_id", "scope"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    preview: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="txt")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    city: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
