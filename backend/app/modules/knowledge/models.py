"""知识库文档元数据与父块表。

- ``knowledge_documents``：文档级元数据（列表 / 去重 / 删除）。
- ``knowledge_parent_chunks``：结构感知切分出的父块正文。父块只存 PostgreSQL，
  不进入向量库；Milvus 的子块通过 ``parent_id`` 回查这里做上下文增强。
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


class KnowledgeParentChunk(Base):
    """父块正文：只写 PostgreSQL，检索命中子块后按 id 回填。

    ``id`` 形如 ``{doc_id}:p{parent_index}``；子块 metadata 中的 ``parent_id``
    与之一一对应。
    """

    __tablename__ = "knowledge_parent_chunks"
    __table_args__ = (
        Index("ix_knowledge_parent_doc", "doc_id"),
        Index("ix_knowledge_parent_owner_scope", "owner_id", "scope"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    city: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    section: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    block_type: Mapped[str] = mapped_column(String(32), nullable=False, default="section")
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
