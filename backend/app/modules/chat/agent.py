"""对话 Agent：LangChain ``create_agent`` + LangGraph checkpointer。

- 会话状态（messages）由 checkpointer 保存在 PostgreSQL；
- 工具：时间 MCP / 12306 MCP + 知识库混合检索（Milvus 稠密+稀疏+Cross-Encoder）；
- 同一 ``thread_id``（= session_id）可跨请求恢复上下文。

当前使用 ``create_agent`` 做原型验证，后续可替换为自定义 LangGraph 工作流，
工具与 checkpointer 的接入方式保持不变。
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from backend.app.core.config import settings
from backend.app.core.database import get_checkpointer
from backend.app.core.logging import get_logger
from backend.app.integrations.llm import get_llm
from backend.app.integrations.mcp import RAIL, TIME, get_mcp_tools
from backend.app.modules.knowledge.retrieval import retrieve_knowledge

logger = get_logger(__name__)

SYSTEM_PROMPT = """你是「旅迹智绘」的 AI 旅行助手，用中文回答。

你可以使用工具获取真实信息：
- 时间工具：查询当前日期 / 时区换算。涉及「今天」「明天」时先确认日期。
- 12306 工具：查询火车票。查询顺序是：先用 get-station-code-of-citys 把城市转成站码，
  再用 get-tickets 查询（date 使用 YYYY-MM-DD，format 使用 text）。不要向用户索要站码。
- 知识库工具 search_knowledge：检索城市攻略、用户上传的旅行笔记与知识库资料。
  回答涉及具体景点/美食/路线/避坑建议时，优先调用它，并在回答中注明「来自知识库」。
当前对话城市：{city}

规则：
1. 票价、余票、车次、时间等实时信息必须来自工具结果，不要编造；工具失败时明确说明。
2. 不虚构酒店地址、景点坐标、价格等易变化信息。
3. 知识库没有覆盖的问题不要假装检索到；资料不足时直接说明。
4. 你的职责是帮用户理清目的地、天数、同行人、预算与节奏；需要完整行程时，
   建议用户点击「用表单生成完整行程」，由行程规划 Agent 结合真实 POI/酒店/天气生成。
5. 回答简洁、具体，必要时给出取舍建议。"""


class KnowledgeSearchInput(BaseModel):
    query: str = Field(description="检索问题，尽量包含城市、景点或具体主题")
    top_k: int = Field(default=4, ge=1, le=8, description="返回资料条数")


def _make_knowledge_tool(city: str, user_id: str) -> StructuredTool:
    """把 city / user_id 绑定进工具闭包，避免模型自行填写归属参数。"""

    async def _search(query: str, top_k: int = 4) -> str:
        try:
            documents = await retrieve_knowledge(
                query,
                city=city or None,
                user_id=user_id or None,
                k=max(1, min(int(top_k or 4), 8)),
            )
        except Exception as exc:
            logger.warning("对话知识库检索失败", error=str(exc))
            return f"知识库检索失败：{exc}"

        if not documents:
            return "知识库未检索到相关内容。"

        parts: list[str] = []
        for index, document in enumerate(documents, start=1):
            metadata = document.metadata or {}
            source = metadata.get("title") or metadata.get("source") or "知识库"
            section = metadata.get("section") or ""
            # section 是 h1/h2/h3 面包屑，通常已含标题；避免重复
            if section and str(source) in section:
                label = section
            elif section:
                label = f"{source} / {section}"
            else:
                label = str(source)
            content = (document.page_content or "").strip()
            if len(content) > 1200:
                content = content[:1200] + "…"
            parts.append(f"[资料{index} 来源:{label}]\n{content}")
        return "\n\n".join(parts)

    return StructuredTool.from_function(
        coroutine=_search,
        name="search_knowledge",
        description=(
            "检索旅迹智绘知识库，返回与管理端城市攻略和用户上传笔记相关的段落。"
            "适合查询具体景点、美食、路线、交通、避坑建议等。"
        ),
        args_schema=KnowledgeSearchInput,
    )


_agents: dict[tuple[str, str], Any] = {}


def get_chat_agent(city: str = "", user_id: str = "") -> Any:
    """按（城市, 用户）缓存对话 Agent；checkpointer 在所有 Agent 间共享。"""
    key = ((city or "").strip(), (user_id or "").strip())
    if key in _agents:
        return _agents[key]

    mcp_tools = list(get_mcp_tools(TIME, RAIL) or [])
    tools = list(mcp_tools)
    if settings.chat.rag_tool_enabled:
        tools.append(_make_knowledge_tool(city=key[0], user_id=key[1]))

    prompt = SYSTEM_PROMPT.format(city=key[0] or "未确定")
    if not mcp_tools:
        prompt += (
            "\n\n注意：当前实时工具不可用。涉及日期、车次、余票等问题时不要编造，"
            "请直接说明暂时无法查询。"
        )
    if not settings.chat.rag_tool_enabled:
        prompt += "\n\n注意：当前知识库工具未启用，涉及攻略细节时请说明无法检索。"

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
