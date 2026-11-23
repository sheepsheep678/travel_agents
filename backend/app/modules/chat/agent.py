"""对话 Agent 工厂：按（城市, 用户）构建带 checkpointer 的对话工作流。

工作流定义在 ``modules.chat.workflow``：意图识别 → 闲聊/推荐/规划/人工/兜底
→ 安全围栏。消息快照由 checkpointer 按 ``thread_id = session_id`` 保存。
"""

from __future__ import annotations

from typing import Any

from backend.app.modules.chat.workflow.graph import build_chat_graph

_graphs: dict[tuple[str, str], Any] = {}


def get_chat_agent(city: str = "", user_id: str = "") -> Any:
    """按（城市, 用户）缓存对话工作流；checkpointer 在所有实例间共享。"""
    key = ((city or "").strip(), (user_id or "").strip())
    if key not in _graphs:
        _graphs[key] = build_chat_graph(city=key[0], user_id=key[1])
    return _graphs[key]


def reset_chat_agents() -> None:
    """清空工作流缓存（测试或 MCP 工具变更后使用）。"""
    _graphs.clear()


def chat_config(session_id: str) -> dict:
    """checkpointer 线程配置：thread_id 即服务端会话 ID。"""
    return {"configurable": {"thread_id": session_id}}
