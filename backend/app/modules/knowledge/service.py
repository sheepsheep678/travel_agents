"""知识库业务：解析、Markdown 优化、父子块切分、PG 父块与 Milvus 子块写入。

- PostgreSQL：``knowledge_documents``（文档元数据）+ ``knowledge_parent_chunks``（父块正文）。
- Milvus：子块（id / 元数据 / 原始文本 / 稠密向量 / BM25 稀疏向量）。
- 写入前先删除同一 ``doc_id`` 的旧父块与旧子块，满足「先删再加」的幂等更新。
- 用户文档归属 ``user_id``（浏览器匿名 ID），与聊天会话解耦。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.exceptions import ExternalServiceError
from backend.app.core.logging import get_logger
from backend.app.integrations.milvus import (
    MilvusUnavailableError,
    adelete_document,
    ainsert_children,
)
from backend.app.modules.knowledge.chunking import chunk_parent_child
from backend.app.modules.knowledge.extractors import (
    KnowledgeValidationError,
    detect_source_type,
    extract_content,
)
from backend.app.modules.knowledge.markdown import optimize_markdown
from backend.app.modules.knowledge.models import (
    KnowledgeDocument,
    KnowledgeParentChunk,
)
from backend.app.modules.knowledge.repository import KnowledgeRepository
from backend.app.modules.knowledge.schemas import KnowledgeItem

logger = get_logger(__name__)

_MAX_CONTENT_CHARS = 200_000


def _preview(text: str, limit: int = 120) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def _derive_title(text: str, filename: str = "") -> str:
    for line in (text or "").splitlines():
        candidate = line.strip().lstrip("#").strip()
        if candidate:
            return candidate[:60]
    if filename:
        return Path(filename).stem[:60]
    return "未命名资料"


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _item_from_model(
    document: KnowledgeDocument, parent_count: int = 0
) -> KnowledgeItem:
    return KnowledgeItem(
        doc_id=document.id,
        title=document.title,
        preview=document.preview,
        source_type=document.source_type,
        chunk_count=document.chunk_count,
        parent_count=parent_count,
        city=document.city,
        source=document.source,
        created_at=document.created_at.isoformat(),
        scope=document.scope,
    )


class KnowledgeService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = KnowledgeRepository(db)

    # ------------------------------------------------------------------
    # 入库
    # ------------------------------------------------------------------

    async def ingest(
        self,
        *,
        user_id: str,
        text: str = "",
        file_data: bytes | None = None,
        filename: str = "",
        scope: str = "user",
        title: str = "",
        city: str = "",
        doc_id: str = "",
        replace: bool = False,
    ) -> KnowledgeItem:
        if scope not in ("user", "admin"):
            raise KnowledgeValidationError("scope 只能是 user 或 admin")
        if scope == "user" and not user_id:
            raise KnowledgeValidationError("缺少 user_id")

        text = (text or "").strip()
        if len(text) > settings.knowledge.max_text_chars:
            raise KnowledgeValidationError(
                f"文本超过 {settings.knowledge.max_text_chars} 字"
            )

        source_type = "txt"
        extraction_method = "text"
        content = text
        if file_data:
            source_type = detect_source_type(filename, file_data)
            file_text, extraction_method = await asyncio.to_thread(
                extract_content, file_data, source_type, filename
            )
            content = f"{text}\n\n{file_text}".strip() if text else file_text

        if not content.strip():
            raise KnowledgeValidationError("没有可入库的内容")
        if len(content) > _MAX_CONTENT_CHARS:
            raise KnowledgeValidationError("内容过长，请拆分后再上传")

        owner_id = user_id if scope == "user" else "admin"
        visibility = "private" if scope == "user" else "public"
        doc_title = (title.strip() or _derive_title(content, filename))[:120]

        # 去重基于「抽取后的原始内容」，避免 LLM 排版结果波动导致重复入库
        content_hash = _sha256(content)
        # 大模型只整理 Markdown 排版，不增删事实；失败自动回退原文
        content = await optimize_markdown(content, source_type, doc_title)

        doc_id = (doc_id or uuid4().hex).strip()
        if not doc_id:
            raise KnowledgeValidationError("doc_id 不能为空")

        existing = await self.repo.get(doc_id, owner_id, scope)
        if not replace:
            # 内容重复：直接返回已有文档，避免重复入库
            same_hash = await self.repo.get_by_hash(owner_id, scope, content_hash)
            if same_hash is not None:
                return _item_from_model(
                    same_hash, await self.repo.count_parents(same_hash.id)
                )
            if existing is not None:
                return _item_from_model(
                    existing, await self.repo.count_parents(existing.id)
                )

        # 先切分：格式错误时直接失败，不破坏旧数据
        parents, children = await asyncio.to_thread(
            chunk_parent_child, content, source_type, doc_title
        )
        if not children:
            raise KnowledgeValidationError("切分后没有内容，请检查文档格式")

        # 先删：Milvus 子块 + PostgreSQL 父块 + 旧文档行
        try:
            await self._purge_existing(doc_id, owner_id, scope)
            await self.repo.flush()
        except Exception as exc:
            await self.repo.rollback()
            raise ExternalServiceError(f"知识库旧数据清理失败: {exc}") from exc

        parent_models = [
            KnowledgeParentChunk(
                id=f"{doc_id}:p{parent.index}",
                doc_id=doc_id,
                owner_id=owner_id,
                scope=scope,
                city=(city or "").strip(),
                title=doc_title,
                source=doc_title if scope == "user" else (filename or "admin"),
                section=parent.section[:512],
                block_type=parent.block_type[:32],
                chunk_index=parent.index,
                content=parent.content,
                content_hash=_sha256(parent.content),
            )
            for parent in parents
        ]

        source_name = doc_title if scope == "user" else (filename or "admin")
        child_rows = [
            {
                "id": f"{doc_id}:c{child.index}",
                "doc_id": doc_id,
                "parent_id": f"{doc_id}:p{child.parent_index}",
                "parent_index": child.parent_index,
                "chunk_index": child.index,
                "scope": scope,
                "owner_id": owner_id,
                "visibility": visibility,
                "city": (city or "").strip(),
                "title": doc_title[:256],
                "source": source_name[:256],
                "source_type": source_type,
                "section": child.section[:512],
                "block_type": child.block_type[:32],
                "content_hash": _sha256(child.content),
                "content": child.content[:8192],
                "text": child.text[:8192],
            }
            for child in children
        ]

        document = KnowledgeDocument(
            id=doc_id,
            owner_id=owner_id,
            scope=scope,
            title=doc_title,
            preview=_preview(content),
            source_type=source_type,
            chunk_count=len(children),
            city=(city or "").strip(),
            source=source_name[:255],
            content_hash=content_hash,
        )
        self.repo.add(document)
        self.repo.add_parents(parent_models)
        await self.repo.flush()

        try:
            await ainsert_children(child_rows)
            await self.repo.commit()
        except Exception as exc:
            await self.repo.rollback()
            try:
                await adelete_document(doc_id, owner_id, scope)
            except Exception:
                logger.warning("回滚 Milvus 子块失败", doc_id=doc_id)
            if isinstance(exc, MilvusUnavailableError):
                raise ExternalServiceError(f"知识库写入失败: {exc}") from exc
            raise ExternalServiceError(f"知识库写入失败: {exc}") from exc

        logger.info(
            "知识库写入完成",
            scope=scope,
            owner_id=owner_id,
            doc_id=doc_id,
            parent_count=len(parents),
            child_count=len(children),
            source_type=source_type,
            extraction_method=extraction_method,
        )
        return _item_from_model(document, parent_count=len(parents))

    async def _purge_existing(self, doc_id: str, owner_id: str, scope: str) -> None:
        """先删 Milvus 子块与 PG 父块/文档行；失败向上抛，避免新旧数据混杂。"""
        try:
            await adelete_document(doc_id, owner_id, scope)
        except MilvusUnavailableError:
            raise
        except Exception as exc:
            logger.warning("删除旧 Milvus 子块失败", doc_id=doc_id, error=str(exc))
            raise

        await self.repo.delete_parents_by_doc(doc_id, owner_id, scope)
        existing = await self.repo.get(doc_id, owner_id, scope)
        if existing is not None:
            await self.repo.delete(existing)

    # ------------------------------------------------------------------
    # 查询 / 删除
    # ------------------------------------------------------------------

    async def list_documents(self, user_id: str) -> list[KnowledgeItem]:
        documents = await self.repo.list_by_owner(user_id, scope="user")
        counts = await self.repo.count_parents_by_doc_ids(
            [document.id for document in documents]
        )
        return [
            _item_from_model(document, counts.get(document.id, 0))
            for document in documents
        ]

    async def delete_document(self, doc_id: str, user_id: str) -> bool:
        document = await self.repo.get(doc_id, user_id, scope="user")
        if document is None:
            return False

        try:
            await adelete_document(doc_id, user_id, "user")
            await self.repo.delete_parents_by_doc(doc_id, user_id, "user")
            await self.repo.delete(document)
            await self.repo.commit()
        except Exception as exc:
            await self.repo.rollback()
            raise ExternalServiceError(f"知识库删除失败: {exc}") from exc

        logger.info("知识库删除完成", doc_id=doc_id, owner_id=user_id)
        return True

    # ------------------------------------------------------------------
    # 管理端语料入库
    # ------------------------------------------------------------------

    async def ingest_admin_file(
        self, path: str | Path, city: str = "", force: bool = True
    ) -> KnowledgeItem:
        """把一个语料文件写入管理端知识库；doc_id 固定为 ``admin:{城市}``。"""
        path = Path(path)
        city_name = (city or path.stem).strip()
        data = await asyncio.to_thread(path.read_bytes)
        return await self.ingest(
            user_id="admin",
            file_data=data,
            filename=path.name,
            scope="admin",
            title="",
            city=city_name,
            doc_id=f"admin:{city_name}",
            replace=force,
        )
