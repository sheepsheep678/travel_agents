"""给已有管理端 chunk 补 scope/owner_id 等 metadata（不重新 embedding）。

用法（务必先停止后端，避免 Chroma 进程内缓存与写入冲突）：
    python -m backend.app.api.migrate_admin_metadata
"""

import hashlib
import logging
import os
import re
from datetime import datetime, timezone

from backend.app.services.rag_component import get_vector_store

logger = logging.getLogger(__name__)


def _derive_title(text: str, source: str) -> str:
    for line in (text or "").splitlines():
        candidate = line.strip().lstrip("#").strip()
        if candidate:
            return candidate[:60]
    stem = os.path.splitext(os.path.basename(source or ""))[0]
    return stem or "管理端资料"


def _preview(text: str, limit: int = 120) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def migrate() -> int:
    store = get_vector_store()
    data = store.get(include=["metadatas", "documents"])
    ids = data.get("ids") or []
    metadatas = data.get("metadatas") or []
    documents = data.get("documents") or []

    if not ids:
        logger.info("集合为空，无需迁移")
        return 0

    grouped: dict[str, list[tuple[str, dict, str]]] = {}
    for index, doc_id in enumerate(ids):
        meta = dict(metadatas[index] or {}) if index < len(metadatas) else {}
        source = str(meta.get("source") or "unknown")
        # 只迁移没有归属的旧 chunk；已有 scope 的用户/管理端上传一律跳过。
        if meta.get("scope"):
            continue
        document = documents[index] if index < len(documents) else ""
        grouped.setdefault(source, []).append((doc_id, meta, document or ""))

    if not grouped:
        logger.info("没有需要迁移的管理端 chunk")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    update_ids: list[str] = []
    update_metas: list[dict] = []

    for source, items in grouped.items():
        total = len(items)
        first_doc = items[0][2]
        title = _derive_title(first_doc, source)
        preview = _preview(first_doc)
        stem = os.path.splitext(os.path.basename(source))[0]
        admin_doc_id = f"admin:{stem or hashlib.sha1(source.encode('utf-8')).hexdigest()[:12]}"

        for chunk_index, (doc_id, meta, document) in enumerate(items):
            meta.update({
                "doc_id": admin_doc_id,
                "session_id": "",
                "owner_id": "admin",
                "scope": "admin",
                "visibility": "public",
                "source_type": "md",
                "title": meta.get("title") or title,
                "preview": meta.get("preview") or preview,
                "city": meta.get("city") or "",
                "chunk_index": chunk_index,
                "chunk_total": total,
                "content_hash": meta.get("content_hash")
                or hashlib.sha256(document.encode("utf-8")).hexdigest(),
                "created_at": meta.get("created_at") or now,
                "extraction_method": "text",
                "block_type": "paragraph",
                "section": meta.get("section") or "",
                "chunk_policy_version": "admin_v1",
            })
            update_ids.append(doc_id)
            update_metas.append(meta)

    store._collection.update(ids=update_ids, metadatas=update_metas)
    logger.info("已迁移 %d 个 chunk，覆盖 %d 个来源文件", len(update_ids), len(grouped))
    return len(update_ids)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
