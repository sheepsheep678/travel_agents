"""知识库元数据的数据库操作。"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.modules.knowledge.models import KnowledgeDocument


class KnowledgeRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_hash(
        self, owner_id: str, scope: str, content_hash: str
    ) -> Optional[KnowledgeDocument]:
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.owner_id == owner_id,
            KnowledgeDocument.scope == scope,
            KnowledgeDocument.content_hash == content_hash,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get(self, doc_id: str, owner_id: str, scope: str) -> Optional[KnowledgeDocument]:
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.id == doc_id,
            KnowledgeDocument.owner_id == owner_id,
            KnowledgeDocument.scope == scope,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_by_owner(self, owner_id: str, scope: str = "user") -> Sequence[KnowledgeDocument]:
        stmt = (
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.owner_id == owner_id,
                KnowledgeDocument.scope == scope,
            )
            .order_by(KnowledgeDocument.created_at.desc())
        )
        return (await self.db.execute(stmt)).scalars().all()

    def add(self, document: KnowledgeDocument) -> KnowledgeDocument:
        self.db.add(document)
        return document

    async def delete(self, document: KnowledgeDocument) -> None:
        await self.db.delete(document)

    async def commit(self) -> None:
        await self.db.commit()

    async def rollback(self) -> None:
        await self.db.rollback()

    async def flush(self) -> None:
        await self.db.flush()
