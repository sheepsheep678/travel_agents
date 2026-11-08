"""用户/管理端知识库的解析、切块与 Chroma 写入。"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from backend.app.models.knowledge import KnowledgeItem
from backend.app.services.config import settings
from backend.app.services.knowledge_extractors import (
    KnowledgeValidationError,
    detect_source_type,
    extract_content,
)
from backend.app.services.rag_component import get_vector_store

logger = logging.getLogger(__name__)

_ARROW_RE = re.compile(r"(?:->|→|⇒|—>|－>)")
_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "，", " "]
_MAX_CONTENT_CHARS = 200_000


def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.knowledge_chunk_size,
        chunk_overlap=settings.knowledge_chunk_overlap,
        separators=_SEPARATORS,
    )


def _markdown_splitter() -> MarkdownHeaderTextSplitter:
    return MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
        strip_headers=False,
    )


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    return (
        "|" in stripped
        and "-" in stripped
        and set(stripped) <= set("|-: ")
    )


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
    limit = max_chars or settings.knowledge_chunk_size
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


def _item_from_meta(meta: dict) -> KnowledgeItem:
    return KnowledgeItem(
        doc_id=str(meta.get("doc_id") or ""),
        title=str(meta.get("title") or "未命名资料"),
        preview=str(meta.get("preview") or ""),
        source_type=str(meta.get("source_type") or "txt"),
        chunk_count=int(meta.get("chunk_total") or 1),
        city=str(meta.get("city") or ""),
        source=str(meta.get("source") or ""),
        created_at=str(meta.get("created_at") or ""),
        scope=str(meta.get("scope") or "user"),
    )


def _find_by_hash(owner_id: str, scope: str, content_hash: str) -> KnowledgeItem | None:
    try:
        data = get_vector_store().get(
            where={
                "$and": [
                    {"owner_id": {"$eq": owner_id}},
                    {"scope": {"$eq": scope}},
                    {"content_hash": {"$eq": content_hash}},
                ]
            },
            include=["metadatas"],
        )
    except Exception as exc:  # 旧集合/异常时不要让上传失败
        logger.warning("知识库去重查询失败: %s", exc)
        return None

    metadatas = data.get("metadatas") or []
    for meta in metadatas:
        if meta:
            return _item_from_meta(meta)
    return None


def ingest(
    *,
    text: str = "",
    file_data: bytes | None = None,
    filename: str = "",
    session_id: str = "",
    scope: str = "user",
    title: str = "",
    city: str = "",
) -> KnowledgeItem:
    """解析并写入一条知识文档；返回抽屉展示用的 item。"""
    if scope not in ("user", "admin"):
        raise KnowledgeValidationError("scope 只能是 user 或 admin")
    if scope == "user" and not session_id:
        raise KnowledgeValidationError("缺少 session_id")

    text = (text or "").strip()
    if len(text) > settings.knowledge_max_text_chars:
        raise KnowledgeValidationError(
            f"文本超过 {settings.knowledge_max_text_chars} 字"
        )

    source_type = "txt"
    extraction_method = "text"
    content = text
    if file_data:
        source_type = detect_source_type(filename, file_data)
        file_text, extraction_method = extract_content(file_data, source_type, filename)
        content = f"{text}\n\n{file_text}".strip() if text else file_text

    if not content.strip():
        raise KnowledgeValidationError("没有可入库的内容")
    if len(content) > _MAX_CONTENT_CHARS:
        raise KnowledgeValidationError("内容过长，请拆分后再上传")

    owner_id = session_id if scope == "user" else "admin"
    visibility = "private" if scope == "user" else "public"
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    existing = _find_by_hash(owner_id, scope, content_hash)
    if existing is not None:
        return existing

    chunks = chunk_document(content, source_type)
    if not chunks:
        raise KnowledgeValidationError("切分后没有内容，请检查文档格式")

    doc_id = uuid4().hex
    doc_title = title.strip() or _derive_title(content, filename)
    preview = _preview(content)
    created_at = datetime.now(timezone.utc).isoformat()
    total = len(chunks)

    documents: list[Document] = []
    ids: list[str] = []
    for index, (chunk_text, block_type, section) in enumerate(chunks):
        meta = {
            "doc_id": doc_id,
            "session_id": owner_id if scope == "user" else "",
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
            "created_at": created_at,
            "extraction_method": extraction_method,
            "block_type": block_type,
            "section": section,
            "source": doc_title if scope == "user" else (filename or "admin"),
            "chunk_policy_version": "user_v1" if scope == "user" else "admin_v1",
        }
        documents.append(Document(page_content=chunk_text, metadata=meta))
        ids.append(f"{doc_id}:{index}")

    get_vector_store().add_documents(documents, ids=ids)
    logger.info(
        "[知识库] 写入 %d 个 chunk: scope=%s owner=%s doc=%s type=%s",
        total, scope, owner_id, doc_id, source_type,
    )

    return KnowledgeItem(
        doc_id=doc_id,
        title=doc_title,
        preview=preview,
        source_type=source_type,
        chunk_count=total,
        city=(city or "").strip(),
        source=doc_title if scope == "user" else (filename or "admin"),
        created_at=created_at,
        scope=scope,
    )


def list_documents(session_id: str) -> list[KnowledgeItem]:
    """列出当前会话上传的文档（不含管理端资料）。"""
    data = get_vector_store().get(
        where={
            "$and": [
                {"owner_id": {"$eq": session_id}},
                {"scope": {"$eq": "user"}},
            ]
        },
        include=["metadatas"],
    )
    metadatas = data.get("metadatas") or []

    by_doc: dict[str, dict] = {}
    for meta in metadatas:
        if not meta:
            continue
        doc_id = str(meta.get("doc_id") or "")
        if doc_id and doc_id not in by_doc:
            by_doc[doc_id] = meta

    items = [_item_from_meta(meta) for meta in by_doc.values()]
    items.sort(key=lambda item: item.created_at, reverse=True)
    return items


def delete_document(doc_id: str, session_id: str) -> bool:
    """只允许删除当前会话自己的 user 文档。"""
    store = get_vector_store()
    data = store.get(
        where={
            "$and": [
                {"doc_id": {"$eq": doc_id}},
                {"owner_id": {"$eq": session_id}},
                {"scope": {"$eq": "user"}},
            ]
        }
    )
    ids = data.get("ids") or []
    if not ids:
        return False
    store.delete(ids=ids)
    logger.info("[知识库] 删除 doc=%s owner=%s，共 %d 个 chunk", doc_id, session_id, len(ids))
    return True
