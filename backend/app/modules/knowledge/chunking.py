"""结构感知 + 递归的父子块切分。

- **父块**：按 Markdown 标题（H1/H2/H3）天然分节；超长章节再用递归切分兜底。
  父块只写 PostgreSQL，不进入向量库，用于检索命中后回填完整上下文。
- **子块**：在父块内部按表格 / 路线 / 段落切分并合并到目标长度，
  再递归兜底。子块写 Milvus，文本会加「文档标题 + 章节」前缀，
  使所有子块共享标题信息（提升 BM25 与向量召回）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from backend.app.core.config import settings

_ARROW_RE = re.compile(r"(?:->|→|⇒|—>|－>)")
_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "，", " "]
_MAX_CHILD_TEXT = 8000


@dataclass
class ParentChunk:
    index: int
    content: str
    section: str = ""
    block_type: str = "section"


@dataclass
class ChildChunk:
    index: int
    parent_index: int
    content: str          # 原始子块文本
    text: str             # 写入 Milvus 的检索文本（标题 + 章节 + 原文）
    section: str = ""
    block_type: str = "paragraph"


# ---------------------------------------------------------------------------
# 递归切分
# ---------------------------------------------------------------------------


def _recursive_splitter(chunk_size: int, chunk_overlap: int):
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=_SEPARATORS,
    )


def _markdown_sections(text: str):
    # 父块按 H1/H2 分节：一个 H2 往往是一个完整主题（如「核心必玩景点」），
    # 其下多个 H3 子主题再切成子块，父块能为子块提供更完整的上下文。
    return MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2")],
        strip_headers=False,
    ).split_text(text)


_H3_RE = re.compile(r"(?m)^###\s+(.+?)\s*$")


def _h3_segments(content: str) -> List[Tuple[str, str]]:
    """把父块按 H3 再分段，返回 [(段落文本, H3 标题)]。"""
    matches = list(_H3_RE.finditer(content or ""))
    if not matches:
        return [((content or "").strip(), "")]

    segments: List[Tuple[str, str]] = []
    if matches[0].start() > 0:
        head = content[: matches[0].start()].strip()
        if head:
            segments.append((head, ""))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        segment = content[match.start(): end].strip()
        if segment:
            segments.append((segment, match.group(1).strip()))
    return segments


def _section_title(metadata: dict) -> str:
    return " / ".join(
        str(metadata[key]).strip()
        for key in ("h1", "h2", "h3")
        if metadata.get(key)
    )


def _is_heading_only(text: str) -> bool:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return bool(lines) and all(line.startswith("#") for line in lines)


# ---------------------------------------------------------------------------
# 块识别（表格 / 路线 / 段落）
# ---------------------------------------------------------------------------


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    return "|" in stripped and "-" in stripped and set(stripped) <= set("|-: ")


def _split_route_line(line: str, limit: int) -> List[str]:
    """超长路线按箭头切开，箭头保留在后一段开头。"""
    if len(line) <= limit:
        return [line]
    parts = re.split(r"(?=(?:->|→|⇒|—>|－>))", line)
    chunks: List[str] = []
    current = ""
    for part in parts:
        if current and len(current) + len(part) > limit:
            chunks.append(current.strip())
            current = part
        else:
            current += part
    if current.strip():
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk]


def _split_blocks(text: str, limit: int, overlap: int) -> List[Tuple[str, str]]:
    """把文本拆成 (block_type, content)：table / route / paragraph。"""
    lines = text.splitlines()
    blocks: List[Tuple[str, str]] = []
    buffer: List[str] = []

    def flush_paragraph() -> None:
        if not buffer:
            return
        paragraph = "\n".join(buffer).strip()
        buffer.clear()
        if paragraph:
            for part in _recursive_splitter(limit, overlap).split_text(paragraph):
                if part.strip():
                    blocks.append(("paragraph", part.strip()))

    index = 0
    while index < len(lines):
        line = lines[index]

        # Markdown 表格：每行单独成块并重复表头，保证列语义完整。
        if (
            line.lstrip().startswith("|")
            and index + 1 < len(lines)
            and _is_table_separator(lines[index + 1])
        ):
            flush_paragraph()
            header = line.strip()
            separator = lines[index + 1].strip()
            index += 2
            rows: List[str] = []
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

        # 路线行：A->B->C / A→B，尽量保持完整。
        if _ARROW_RE.search(line):
            flush_paragraph()
            for part in _split_route_line(line.strip(), limit):
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
    blocks: Sequence[Tuple[str, str]], max_chars: int
) -> List[Tuple[str, str]]:
    """把相邻短段落/路线合并到接近 max_chars；表格不合并。"""
    merged: List[Tuple[str, str]] = []
    buffer: List[str] = []
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

        if buffer and buffer_len + len(content) + 2 > max_chars:
            flush()

        if not buffer:
            buffer_type = block_type
            buffer_len = 0
        elif block_type == "route":
            buffer_type = "route"

        buffer.append(content)
        buffer_len += len(content) + 2

    flush()
    return merged


# ---------------------------------------------------------------------------
# 父子块切分
# ---------------------------------------------------------------------------


def _child_text(title: str, section: str, content: str) -> str:
    title = (title or "").strip()
    section = (section or "").strip()
    if section and title and title in section:
        # section 是 h1/h2/h3 面包屑，通常已包含文档标题，避免重复
        prefix = section
    else:
        prefix = " / ".join(part for part in (title, section) if part)
    if not prefix:
        return content
    if content.startswith(prefix):
        return content
    text = f"{prefix}\n{content}"
    if len(text) > _MAX_CHILD_TEXT:
        # 极端长标题/内容：保留标题前缀并截断正文，避免超过 Milvus VARCHAR 上限
        room = max(0, _MAX_CHILD_TEXT - len(prefix) - 1)
        text = f"{prefix}\n{content[:room]}"
    return text


def _parent_contents(
    section_text: str, section: str, parent_size: int, parent_overlap: int
) -> List[ParentChunk]:
    """把单个 Markdown 章节转换成 1..N 个父块。"""
    parent_size = max(200, parent_size)
    parent_overlap = min(parent_size // 2, max(0, parent_overlap))
    section_text = (section_text or "").strip()
    if not section_text:
        return []

    pieces = (
        [section_text]
        if len(section_text) <= parent_size
        else _recursive_splitter(parent_size, parent_overlap).split_text(section_text)
    )
    parents: List[ParentChunk] = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        # 章节只有标题没有正文时跳过，避免父块无信息
        if _is_heading_only(piece):
            continue
        parents.append(ParentChunk(index=0, content=piece, section=section))
    return parents


def chunk_parent_child(
    text: str,
    source_type: str,
    title: str = "",
    *,
    parent_size: Optional[int] = None,
    child_size: Optional[int] = None,
    child_overlap: Optional[int] = None,
) -> Tuple[List[ParentChunk], List[ChildChunk]]:
    """返回 (父块列表, 子块列表)；index 在整个文档内连续编号。"""
    text = (text or "").strip()
    if not text:
        return [], []

    parent_limit = max(
        200, parent_size if parent_size is not None else settings.knowledge.parent_chunk_size
    )
    parent_overlap = min(
        parent_limit // 2, max(0, settings.knowledge.parent_chunk_overlap)
    )
    child_limit = max(
        120, child_size if child_size is not None else settings.knowledge.child_chunk_size
    )
    overlap = max(
        0,
        child_overlap
        if child_overlap is not None
        else settings.knowledge.child_chunk_overlap,
    )

    parents: List[ParentChunk] = []
    # md / txt 都先按 Markdown 标题做结构感知分节；无标题时整体作为一节。
    try:
        sections = _markdown_sections(text)
    except Exception:
        sections = []
    if not sections:
        sections = [_FallbackSection(text, {})]

    for section_doc in sections:
        metadata = getattr(section_doc, "metadata", {}) or {}
        section = _section_title(metadata)
        content = getattr(section_doc, "page_content", "") or ""
        for item in _parent_contents(content, section, parent_limit, parent_overlap):
            item.index = len(parents)
            parents.append(item)

    if not parents:
        # 兜底：至少保留一段原文
        parents = [ParentChunk(index=0, content=text, section="", block_type="section")]

    children: List[ChildChunk] = []

    for parent in parents:
        # 父块内再按 H3 子标题分段，让子块带上更精确的章节信息
        for segment_text, h3_title in _h3_segments(parent.content):
            child_section = (
                f"{parent.section} / {h3_title}"
                if parent.section and h3_title
                else (h3_title or parent.section)
            )
            blocks = _split_blocks(segment_text, child_limit, overlap)
            merged = _merge_blocks(blocks, child_limit)
            if not merged:
                merged = [("paragraph", segment_text)]

            for block_type, content in merged:
                content = content.strip()
                if not content:
                    continue
                # 单块仍超长（例如超长表格行）时递归兜底
                pieces = (
                    [content]
                    if len(content) <= child_limit * 1.5
                    else _recursive_splitter(child_limit, overlap).split_text(content)
                )
                for piece in pieces:
                    piece = piece.strip()
                    if not piece:
                        continue
                    if block_type == "paragraph" and _is_heading_only(piece):
                        continue
                    index = len(children)
                    children.append(
                        ChildChunk(
                            index=index,
                            parent_index=parent.index,
                            content=piece,
                            text=_child_text(title, child_section, piece),
                            section=child_section,
                            block_type=block_type,
                        )
                    )

    return parents, children


class _FallbackSection:
    """MarkdownHeaderTextSplitter 异常时的最小结构。"""

    def __init__(self, page_content: str, metadata: dict) -> None:
        self.page_content = page_content
        self.metadata = metadata
