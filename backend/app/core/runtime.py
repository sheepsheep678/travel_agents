"""运行期事件循环辅助。

Windows 上：
- psycopg 的 async 连接池不能在 ``ProactorEventLoop`` 中运行；
- MCP 的 stdio 子进程又需要 ``ProactorEventLoop``。

因此应用主循环保持 Proactor（MCP stdio 可用），checkpointer 的连接池在
``core/database.py`` 中放到独立的 SelectorEventLoop 线程里执行。
"""

from __future__ import annotations

import asyncio
import sys


def proactor_loop_factory(use_subprocess: bool = False):
    """uvicorn 的 ``loop`` 参数：返回一个**事件循环实例**。

    uvicorn 对自定义 ``loop`` 字符串会直接把它交给 ``asyncio.Runner``，
    Runner 会无参调用一次并要求返回 loop 实例（不能返回 loop 类）。
    """
    if sys.platform == "win32":
        return asyncio.ProactorEventLoop()
    return asyncio.SelectorEventLoop()
