"""对话 Agent：LangChain ``create_agent`` + LangGraph checkpointer。

- 会话状态（messages）由 checkpointer 保存在 PostgreSQL；
- 工具使用时间 MCP 与 12306 MCP；
- 同一 ``thread_id``（= session_id）可跨请求恢复上下文。
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent

from backend.app.core.database import get_checkpointer
from backend.app.integrations.llm import get_llm
from backend.app.integrations.mcp import RAIL, TIME, get_mcp_tools

SYSTEM_PROMPT = """你是「旅迹智绘」的 AI 旅行助手，用中文回答。

你可以使用工具获取真实信息：
- 时间工具：查询当前日期 / 时区换算。涉及「今天」「明天」时先确认日期。
- 12306 工具：查询火车票。查询顺序是：先用 get-station-code-of-citys 把城市转成站码，
  再用 get-tickets 查询（date 使用 YYYY-MM-DD，format 使用 text）。不要向用户索要站码。
当前对话城市：{city}

规则：
1. 票价、余票、车次、时间等实时信息必须来自工具结果，不要编造；工具失败时明确说明。
2. 不虚构酒店地址、景点坐标、价格等易变化信息。
3. 你的职责是帮用户理清目的地、天数、同行人、预算与节奏；需要完整行程时，
   建议用户点击「用表单生成完整行程」，由行程规划 Agent 结合真实 POI/酒店/天气生成。
4. 回答简洁、具体，必要时给出取舍建议。"""

_agents: dict[str, Any] = {}


def get_chat_agent(city: str = "") -> Any:
    """按城市缓存对话 Agent；checkpointer 在所有 Agent 间共享。"""
    key = (city or "").strip()
    if key not in _agents:
        tools = get_mcp_tools(TIME, RAIL)
        prompt = SYSTEM_PROMPT.format(city=key or "未确定")
        if not tools:
            prompt += (
                "\n\n注意：当前实时工具不可用。涉及日期、车次、余票等问题时不要编造，"
                "请直接说明暂时无法查询。"
            )
        _agents[key] = create_agent(
            model=get_llm(),
            tools=tools,
            system_prompt=prompt,
            checkpointer=get_checkpointer(),
        )
    return _agents[key]


def reset_chat_agents() -> None:
    """清空 Agent 缓存（测试或 MCP 工具变更后使用）。"""
    _agents.clear()


def chat_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}
