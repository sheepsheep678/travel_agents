"""知识库业务：解析、切块、PG 元数据与 Chroma 向量写入。

- PostgreSQL：文档级元数据（列表 / 去重 / 删除）。
- Chroma：切块后的向量与检索用 metadata。
- 用户文档归属 ``user_id``（浏览器匿名 ID），与聊天会话解耦。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from uuid import uuid4

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.exceptions import ExternalServiceError
from backend.app.core.logging import get_logger
from backend.app.integrations.chroma import get_vector_store
from backend.app.modules.knowledge.extractors import (
    KnowledgeValidationError,
    detect_source_type,
    extract_content,
)
from backend.app.modules.knowledge.models import KnowledgeDocument
from backend.app.modules.knowledge.repository import KnowledgeRepository
from backend.app.modules.knowledge.schemas import KnowledgeItem

logger = get_logger(__name__)

_ARROW_RE = re.compile(r"(?:->|→|⇒|—>|－>)")
_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "，", " "]
_MAX_CONTENT_CHARS = 200_000


def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.knowledge.chunk_size,
        chunk_overlap=settings.knowledge.chunk_overlap,
        separators=_SEPARATORS,
    )


def _markdown_splitter() -> MarkdownHeaderTextSplitter:
    return MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
        strip_headers=False,
    )


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    return "|" in stripped and "-" in stripped and set(stripped) <= set("|-: ")


def _split_route_line(line: str) -> list[str]:
    """超长路线按箭头切开，箭头保留在后一段开头。"""
    if len(line) <= 800:
        return [line]
    parts = re.split(r"(?=(?:->|→|⇒|—>|－>))", line)
    chunks, current = [], ""
    for part in parts:
        if current and len(current) + len(part) > 800:
            chunks.append(current.strip())
            current = part
        else:
            current += part
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c]


def _split_blocks(text: str) -> list[tuple[str, str]]:
    """把一段文本拆成 (block_type, content)：table/route/paragraph。"""
    lines = text.splitlines()
    blocks: list[tuple[str, str]] = []
    buffer: list[str] = []

    def flush_paragraph() -> None:
        if not buffer:
            return
        paragraph = "\n".join(buffer).strip()
        buffer.clear()
        if paragraph:
            for part in _splitter().split_text(paragraph):
                if part.strip():
                    blocks.append(("paragraph", part.strip()))

    index = 0
    while index < len(lines):
        line = lines[index]

        # Markdown 表格：表头 + 分隔行 + N 行数据；每行单独成块并重复表头。
        if (
            line.lstrip().startswith("|")
            and index + 1 < len(lines)
            and _is_table_separator(lines[index + 1])
        ):
            flush_paragraph()
            header = line.strip()
            separator = lines[index + 1].strip()
            index += 2
            rows = []
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                row = lines[index].strip()
                if row:
                    rows.append(row)
                index += 1
            if rows:
                for row in rows:
                    blocks.append(("table", f"{header}\n{separator}\n{row}"))
            else:
                blocks.append(("paragraph", f"{header}\n{separator}"))
            continue

        # 路线行：A->B->C / A→B 等，保持完整，不按字数切断。
        if _ARROW_RE.search(line):
            flush_paragraph()
            for part in _split_route_line(line.strip()):
                blocks.append(("route", part))
            index += 1
            continue

        if not line.strip():
            flush_paragraph()
            index += 1
            continue

        buffer.append(line)
        index += 1

    flush_paragraph()
    return blocks


def _merge_blocks(
    blocks: list[tuple[str, str]],
    max_chars: int | None = None,
) -> list[tuple[str, str]]:
    """把相邻的短段落/路线合并到接近 chunk_size，避免一张图切出几十个碎片。

    表格不参与合并：每行必须保留自己的表头，保证列语义完整。
    """
    limit = max_chars or settings.knowledge.chunk_size
    merged: list[tuple[str, str]] = []
    buffer: list[str] = []
    buffer_len = 0
    buffer_type = "paragraph"

    def flush() -> None:
        if buffer:
            content = "\n".join(buffer).strip()
            if content:
                merged.append((buffer_type, content))
            buffer.clear()

    for block_type, content in blocks:
        content = (content or "").strip()
        if not content:
            continue

        if block_type == "table":
            flush()
            merged.append((block_type, content))
            continue

        if buffer and buffer_len + len(content) + 2 > limit:
            flush()

        if not buffer:
            buffer_type = block_type
            buffer_len = 0
        elif block_type == "route":
            # 路线和相邻段落合并时，整块标记为 route，方便后续检索按路线过滤。
            buffer_type = "route"

        buffer.append(content)
        buffer_len += len(content) + 2

    flush()
    return merged


def _is_heading_only(text: str) -> bool:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return bool(lines) and all(line.startswith("#") for line in lines)


def chunk_document(text: str, source_type: str) -> list[tuple[str, str, str]]:
    """返回 [(chunk 内容, block_type, section)]。"""
    text = (text or "").strip()
    if not text:
        return []

    chunks: list[tuple[str, str, str]] = []
    if source_type == "md":
        sections = _markdown_splitter().split_text(text)
        for section_doc in sections:
            section = " / ".join(
                section_doc.metadata[key]
                for key in ("h1", "h2", "h3")
                if section_doc.metadata.get(key)
            )
            for block_type, content in _merge_blocks(_split_blocks(section_doc.page_content)):
                if block_type == "paragraph" and _is_heading_only(content):
                    continue
                chunks.append((content, block_type, section))
    else:
        for block_type, content in _merge_blocks(_split_blocks(text)):
            if block_type == "paragraph" and _is_heading_only(content):
                continue
            chunks.append((content, block_type, ""))
    return chunks


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


def _item_from_model(document: KnowledgeDocument) -> KnowledgeItem:
    return KnowledgeItem(
        doc_id=document.id,
        title=document.title,
        preview=document.preview,
        source_type=document.source_type,
        chunk_count=document.chunk_count,
        city=document.city,
        source=document.source,
        created_at=document.created_at.isoformat(),
        scope=document.scope,
    )


class KnowledgeService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = KnowledgeRepository(db)

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
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        existing = await self.repo.get_by_hash(owner_id, scope, content_hash)
        if existing is not None:
            return _item_from_model(existing)

        chunks = await asyncio.to_thread(chunk_document, content, source_type)
        if not chunks:
            raise KnowledgeValidationError("切分后没有内容，请检查文档格式")

        doc_id = uuid4().hex
        doc_title = title.strip() or _derive_title(content, filename)
        preview = _preview(content)
        total = len(chunks)

        documents: list[Document] = []
        ids: list[str] = []
        for index, (chunk_text, block_type, section) in enumerate(chunks):
            meta = {
                "doc_id": doc_id,
                "user_id": owner_id if scope == "user" else "",
                "owner_id": owner_id,
                "scope": scope,
                "visibility": visibility,
                "source_type": source_type,
                "title": doc_title,
                "preview": preview,
                "city": (city or "").strip(),
                "chunk_index": index,
                "chunk_total": total,
                "content_hash": content_hash,
                "extraction_method": extraction_method,
                "block_type": block_type,
                "section": section,
                "source": doc_title if scope == "user" else (filename or "admin"),
                "chunk_policy_version": "user_v1" if scope == "user" else "admin_v1",
            }
            documents.append(Document(page_content=chunk_text, metadata=meta))
            ids.append(f"{doc_id}:{index}")

        document = KnowledgeDocument(
            id=doc_id,
            owner_id=owner_id,
            scope=scope,
            title=doc_title,
            preview=preview,
            source_type=source_type,
            chunk_count=total,
            city=(city or "").strip(),
            source=doc_title if scope == "user" else (filename or "admin"),
            content_hash=content_hash,
        )
        self.repo.add(document)
        await self.repo.flush()

        store = get_vector_store()
        try:
            await asyncio.to_thread(store.add_documents, documents, ids=ids)
            await self.repo.commit()
        except Exception as exc:
            await self.repo.rollback()
            try:
                await asyncio.to_thread(store.delete, ids=ids)
            except Exception:
                logger.warning("回滚 Chroma 分块失败", doc_id=doc_id)
            raise ExternalServiceError(f"知识库写入失败: {exc}") from exc

        logger.info(
            "知识库写入完成",
            scope=scope,
            owner_id=owner_id,
            doc_id=doc_id,
            chunk_count=total,
            source_type=source_type,
        )
        return _item_from_model(document)

    async def list_documents(self, user_id: str) -> list[KnowledgeItem]:
        documents = await self.repo.list_by_owner(user_id, scope="user")
        return [_item_from_model(document) for document in documents]

    async def delete_document(self, doc_id: str, user_id: str) -> bool:
        document = await self.repo.get(doc_id, user_id, scope="user")
        if document is None:
            return False

        store = get_vector_store()
        try:
            data = await asyncio.to_thread(
                store.get,
                where={
                    "$and": [
                        {"doc_id": {"$eq": doc_id}},
                        {"owner_id": {"$eq": user_id}},
                        {"scope": {"$eq": "user"}},
                    ]
                },
            )
            ids = data.get("ids") or []
            if ids:
                await asyncio.to_thread(store.delete, ids=ids)
            await self.repo.delete(document)
            await self.repo.commit()
        except Exception as exc:
            await self.repo.rollback()
            raise ExternalServiceError(f"知识库删除失败: {exc}") from exc

        logger.info("知识库删除完成", doc_id=doc_id, owner_id=user_id)
        return True
