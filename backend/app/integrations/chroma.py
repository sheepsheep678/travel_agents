"""本地知识库向量检索（Chroma）。

设计要点：入库脚本与本模块共用 get_vector_store()，保证「集合名 / 距离度量 / 嵌入模型」
在写入侧和查询侧完全一致 —— Chroma 的 get_or_create 语义下，已存在的集合会忽略新传入的
configuration，一旦两侧不一致就会出现难以排查的检索质量问题。
"""

from __future__ import annotations

import threading
from typing import Optional

from langchain_chroma import Chroma

from backend.app.agent.constants import RAG_TOP_K
from backend.app.core.config import settings
from backend.app.integrations.llm import get_embedding_model

# 显式声明余弦距离：langchain-chroma 向 chromadb 传 embedding_function=None，
# 而 chromadb 在无 EF 时 space 默认回落 "l2"，不写就等于沿用旧 SQLite-vec 的 L2 行为。
# 硬约束：集合创建后 configuration 不可改，切换度量必须删除 chroma_dir 重新入库。
_vector_store: Optional[Chroma] = None
_init_lock = threading.Lock()


def _collection_configuration() -> dict:
    return {"hnsw": {"space": settings.rag.chroma_distance}}


def get_vector_store() -> Chroma:
    """惰性构建 Chroma 单例（入库脚本与 API 进程共用同一份构造逻辑）。"""
    global _vector_store
    if _vector_store is None:
        with _init_lock:
            if _vector_store is None:
                _vector_store = Chroma(
                    collection_name=settings.rag.collection,
                    embedding_function=get_embedding_model(),
                    persist_directory=settings.rag.chroma_dir,
                    collection_configuration=_collection_configuration(),
                )
    return _vector_store


async def aretrieve(
    query: str,
    k: int = RAG_TOP_K,
    city: Optional[str] = None,
    user_id: Optional[str] = None,
):
    """异步检索；把 city 与数据归属过滤下推到 Chroma。

    过滤规则：
    - 有 user_id：管理端当前城市内容 + 当前用户自己的全部 user 内容
      （用户自己的笔记不按城市过滤，避免上传时没填城市就检索不到）；
    - 无 user_id：只召回管理端当前城市内容，避免把其他用户的私有上传带进规划。

    参数名必须是 filter=（写成 where= 会在 __query_collection 里与位置参数冲突报
    TypeError）；空字符串不传过滤条件，否则匹配不到任何文档。
    """
    if user_id:
        user_clause = {
            "$and": [
                {"scope": {"$eq": "user"}},
                {"owner_id": {"$eq": user_id}},
            ]
        }
        if city:
            admin_clause = {
                "$and": [
                    {"scope": {"$eq": "admin"}},
                    {"city": {"$eq": city}},
                ]
            }
        else:
            admin_clause = {"scope": {"$eq": "admin"}}
        where = {"$or": [admin_clause, user_clause]}
    elif city:
        where = {
            "$and": [
                {"scope": {"$eq": "admin"}},
                {"city": {"$eq": city}},
            ]
        }
    else:
        where = {"scope": {"$eq": "admin"}}

    return await get_vector_store().asimilarity_search(query, k=k, filter=where)
