"""本地知识库检索（Chroma 向量库）

设计要点：入库脚本与本模块共用 get_vector_store()，保证「集合名 / 距离度量 / 嵌入模型」
在写入侧和查询侧完全一致 —— Chroma 的 get_or_create 语义下，已存在的集合会忽略新传入的
configuration，一旦两侧不一致就会出现难以排查的检索质量问题。
"""

import threading
from typing import Optional

from langchain_chroma import Chroma

from backend.app.constants import RAG_TOP_K
from backend.app.nodes.llm import get_embedding_model
from backend.app.services.config import settings

# 显式声明余弦距离：langchain-chroma 向 chromadb 传 embedding_function=None，
# 而 chromadb 在无 EF 时 space 默认回落 "l2"，不写就等于沿用旧 SQLite-vec 的 L2 行为。
# 硬约束：集合创建后 configuration 不可改，切换度量必须删除 chroma_dir 重新入库。
_vector_store: Optional[Chroma] = None
_init_lock = threading.Lock()


def _collection_configuration() -> dict:
    return {"hnsw": {"space": settings.chroma_distance}}


def get_vector_store() -> Chroma:
    """惰性构建 Chroma 单例（入库脚本与 API 进程共用同一份构造逻辑）

    chromadb 的 PersistentClient 底层按 persist_directory 在 SharedSystemClient 做类级
    缓存（带锁），同路径返回同一个 System；集合句柄不可变，并发读安全。这里再缓存一层
    Chroma 对象，避免每轮查询重复构造。锁只保护构造，不串行化查询。
    """
    global _vector_store
    if _vector_store is None:
        with _init_lock:
            if _vector_store is None:
                _vector_store = Chroma(
                    collection_name=settings.collection,
                    embedding_function=get_embedding_model(),
                    persist_directory=settings.chroma_dir,
                    collection_configuration=_collection_configuration(),
                )
    return _vector_store


async def aretrieve(query: str, k: int = RAG_TOP_K, city: Optional[str] = None):
    """异步检索；city 非空时把 metadata 过滤下推到 Chroma

    langchain-chroma 没有真正的异步实现，asimilarity_search 内部是 run_in_executor
    线程池卸载，不会阻塞事件循环，因此无需自己再写 to_thread。

    参数名必须是 filter=（写成 where= 会在 __query_collection 里与位置参数冲突报
    TypeError）。{"city": x} 是 {"city": {"$eq": x}} 的简写；必须保留 if 判断，
    空字符串会匹配不到任何文档。
    """
    kwargs = {"k": k}
    if city:
        kwargs["filter"] = {"city": city}
    return await get_vector_store().asimilarity_search(query, **kwargs)
