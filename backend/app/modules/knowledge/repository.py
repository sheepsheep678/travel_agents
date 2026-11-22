"""知识库元数据与父块的数据库操作。"""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.modules.knowledge.models import (
    KnowledgeDocument,
    KnowledgeParentChunk,
)


class KnowledgeRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # 文档级元数据
    # ------------------------------------------------------------------

    async def get_by_hash(
        self, owner_id: str, scope: str, content_hash: str
    ) -> Optional[KnowledgeDocument]:
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.owner_id == owner_id,
            KnowledgeDocument.scope == scope,
            KnowledgeDocument.content_hash == content_hash,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get(
        self, doc_id: str, owner_id: str, scope: str
    ) -> Optional[KnowledgeDocument]:
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.id == doc_id,
            KnowledgeDocument.owner_id == owner_id,
            KnowledgeDocument.scope == scope,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, doc_id: str) -> Optional[KnowledgeDocument]:
        stmt = select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_by_owner(
        self, owner_id: str, scope: str = "user"
    ) -> Sequence[KnowledgeDocument]:
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

    # ------------------------------------------------------------------
    # 父块
    # ------------------------------------------------------------------

    def add_parents(self, parents: Iterable[KnowledgeParentChunk]) -> None:
        self.db.add_all(list(parents))

    async def delete_parents_by_doc(
        self, doc_id: str, owner_id: str, scope: str
    ) -> None:
        await self.db.execute(
            delete(KnowledgeParentChunk).where(
                KnowledgeParentChunk.doc_id == doc_id,
                KnowledgeParentChunk.owner_id == owner_id,
                KnowledgeParentChunk.scope == scope,
            )
        )

    async def get_parents_by_ids(
        self, ids: Sequence[str]
    ) -> Sequence[KnowledgeParentChunk]:
        if not ids:
            return []
        stmt = select(KnowledgeParentChunk).where(
            KnowledgeParentChunk.id.in_(list(ids))
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def count_parents(self, doc_id: str) -> int:
        stmt = select(func.count(KnowledgeParentChunk.id)).where(
            KnowledgeParentChunk.doc_id == doc_id
        )
        return int((await self.db.execute(stmt)).scalar() or 0)

    async def count_parents_by_doc_ids(
        self, doc_ids: Sequence[str]
    ) -> Dict[str, int]:
        if not doc_ids:
            return {}
        stmt = (
            select(
                KnowledgeParentChunk.doc_id,
                func.count(KnowledgeParentChunk.id),
            )
            .where(KnowledgeParentChunk.doc_id.in_(list(doc_ids)))
            .group_by(KnowledgeParentChunk.doc_id)
        )
        rows = (await self.db.execute(stmt)).all()
        return {row[0]: int(row[1]) for row in rows}

    # ------------------------------------------------------------------
    # 事务
    # ------------------------------------------------------------------

    async def commit(self) -> None:
        await self.db.commit()

    async def rollback(self) -> None:
        await self.db.rollback()

    async def flush(self) -> None:
        await self.db.flush()
