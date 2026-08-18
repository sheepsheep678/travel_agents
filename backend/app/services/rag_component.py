import asyncio
import sqlite3

import sqlite_vec
from langchain_community.vectorstores import SQLiteVec

from backend.app.nodes.llm import get_embedding_model
from backend.app.services.config import settings


def _connect() -> sqlite3.Connection:
    """每次新建连接并加载 sqlite_vec 扩展（连接隔离，规避并发问题）"""
    connection = sqlite3.connect(settings.db_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)
    return connection


def _sync_search(query: str, k: int):
    """同步检索：查完立即关闭连接"""
    connection = _connect()
    try:
        vec_store = SQLiteVec(
            table=settings.table,
            connection=connection,
            db_file=settings.db_path,
            embedding=get_embedding_model(),
        )
        retriever = vec_store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": k},
        )
        return retriever.invoke(query)
    finally:
        connection.close()


async def aretrieve(query: str, k: int = 4):
    """异步入口：把同步检索丢到线程池执行，不阻塞事件循环"""
    return await asyncio.to_thread(_sync_search, query, k)