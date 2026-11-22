"""知识库混合检索：Milvus 子块召回 → PostgreSQL 父块回填。

检索流程
--------
1. 条件过滤：管理端内容按 ``city`` 过滤；用户内容按 ``owner_id`` 过滤。
2. 多路召回：稠密向量（DashScope Embedding）+ BM25 稀疏向量（Milvus Function）。
3. 融合重排：RRF 融合候选后交给 DashScope Cross-Encoder（gte-rerank）精排。
4. 父块增强：命中子块的 ``parent_id`` 回查 PostgreSQL ``knowledge_parent_chunks``，
   用父块正文替换子块正文加入提示词，兼顾检索精度与上下文完整性。

Milvus 不可用时返回空结果（规划继续但无知识库上下文），不会自动降级到其他向量库。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from langchain_core.documents import Document
from sqlalchemy import select

from backend.app.agent.constants import RAG_TOP_K
from backend.app.core.config import settings
from backend.app.core.database import get_session_factory
from backend.app.core.logging import get_logger
from backend.app.integrations.milvus import RetrievalHit, ahybrid_search
from backend.app.modules.knowledge.models import KnowledgeParentChunk

logger = get_logger(__name__)

_MAX_PARENT_CHARS = 4000
_DEFAULT_SOURCE = "旅迹智绘"


def _quote(value: str) -> str:
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def build_filter(city: Optional[str] = None, user_id: Optional[str] = None) -> str:
    """构造 Milvus 过滤表达式。

    - 有 user_id：管理端当前城市内容 + 当前用户自己的全部内容；
    - 无 user_id：只召回管理端当前城市内容，避免把其他用户的私有上传带进规划。
    """
    city = (city or "").strip()
    user_id = (user_id or "").strip()

    if city:
        admin_clause = f"scope == \"admin\" and city == {_quote(city)}"
    else:
        admin_clause = 'scope == "admin"'

    if not user_id:
        return admin_clause
    user_clause = f"scope == \"user\" and owner_id == {_quote(user_id)}"
    return f"({admin_clause}) or ({user_clause})"


async def _fetch_parents(ids: Sequence[str]) -> Dict[str, KnowledgeParentChunk]:
    if not ids:
        return {}
    try:
        factory = get_session_factory()
    except RuntimeError:
        logger.warning("数据库未初始化，父块回填降级为子块文本")
        return {}

    try:
        async with factory() as db:
            rows = await db.execute(
                select(KnowledgeParentChunk).where(
                    KnowledgeParentChunk.id.in_(list(ids))
                )
            )
            return {row.id: row for row in rows.scalars().all()}
    except Exception as exc:
        logger.warning("读取父块失败，降级为子块文本", error=str(exc))
        return {}


def _document_from_hit(
    hit: RetrievalHit, parent: Optional[KnowledgeParentChunk]
) -> Document:
    content = (parent.content if parent is not None else hit.content or hit.text) or ""
    if len(content) > _MAX_PARENT_CHARS:
        content = content[:_MAX_PARENT_CHARS] + "…"

    metadata = {
        "source": (
            parent.source
            if parent is not None and parent.source
            else hit.metadata.get("source") or _DEFAULT_SOURCE
        ),
        "title": (
            parent.title
            if parent is not None
            else hit.metadata.get("title") or ""
        ),
        "city": (
            parent.city
            if parent is not None
            else hit.metadata.get("city") or ""
        ),
        "section": (
            parent.section
            if parent is not None
            else hit.metadata.get("section") or ""
        ),
        "doc_id": hit.doc_id or (parent.doc_id if parent is not None else ""),
        "parent_id": hit.parent_id or (parent.id if parent is not None else ""),
        "chunk_id": hit.id,
        "child_text": hit.content or hit.text,
        "score": hit.score,
        "dense_score": hit.dense_score,
        "sparse_score": hit.sparse_score,
        "rerank_score": hit.rerank_score,
        "retrieval": hit.retrieval,
        "backend": "milvus",
        "scope": hit.metadata.get("scope") or "",
        "owner_id": hit.metadata.get("owner_id") or "",
    }
    return Document(page_content=content, metadata=metadata)


async def retrieve_knowledge(
    query: str,
    *,
    city: Optional[str] = None,
    user_id: Optional[str] = None,
    k: Optional[int] = None,
) -> List[Document]:
    """混合检索并回填父块；返回的 Document 正文即父块内容。"""
    query = (query or "").strip()
    if not query:
        return []

    top_k = max(1, int(k or settings.milvus.final_top_k or RAG_TOP_K))
    expr = build_filter(city, user_id)
    try:
        hits = await ahybrid_search(query, expr=expr, limit=top_k)
    except Exception as exc:
        logger.warning("Milvus 混合检索失败，知识库上下文为空", error=str(exc))
        return []

    if not hits:
        return []

    parent_ids = [hit.parent_id for hit in hits if hit.parent_id]
    parents = await _fetch_parents(parent_ids)

    documents: List[Document] = []
    seen_parents: set[str] = set()
    for hit in hits:
        key = hit.parent_id or hit.id
        if key in seen_parents:
            continue
        seen_parents.add(key)
        documents.append(_document_from_hit(hit, parents.get(hit.parent_id)))
        if len(documents) >= top_k:
            break

    logger.info(
        "知识库检索完成",
        hits=len(hits),
        parents=len(parents),
        documents=len(documents),
        city=city or "",
        user_id=user_id or "",
    )
    return documents


async def knowledge_stats() -> dict:
    """检索层调试信息：Milvus 集合统计。"""
    from backend.app.integrations.milvus import stats as milvus_stats

    return {"milvus": milvus_stats()}
