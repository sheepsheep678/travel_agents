"""对话工作流的工具装配：MCP 工具 + 绑定 city/user 的知识库检索工具。"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.integrations.mcp import get_mcp_tools
from backend.app.modules.chat.workflow.prompts import PLAN_SYSTEM, RECOMMEND_SYSTEM
from backend.app.modules.knowledge.retrieval import retrieve_knowledge

logger = get_logger(__name__)


class KnowledgeSearchInput(BaseModel):
    query: str = Field(description="检索问题，尽量包含城市、景点或具体主题")
    top_k: int = Field(default=4, ge=1, le=8, description="返回资料条数")


def _make_knowledge_tool(city: str, user_id: str) -> StructuredTool:
    """把 city / user_id 绑定进工具闭包，避免模型自行填写归属参数。"""

    async def _search(query: str, top_k: int = 4) -> str:
        """检索知识库并返回父块段落。"""
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
            "检索旅迹智绘知识库，返回城市攻略和用户上传笔记的段落。"
            "适合查询具体景点、美食、路线、交通、避坑建议。"
        ),
        args_schema=KnowledgeSearchInput,
    )


def collect_tools(city: str, user_id: str) -> list[BaseTool]:
    """收集对话工作流可用的全部工具（高德 + 时间 + 12306 + 知识库）。"""
    tools: list[BaseTool] = list(get_mcp_tools() or [])
    if settings.chat.rag_tool_enabled:
        tools.append(_make_knowledge_tool(city=city, user_id=user_id))
    return tools


def build_tool_agent(
    kind: str,
    city: str,
    user_id: str,
    model: BaseChatModel,
    tools: list[BaseTool],
) -> Any:
    """构建推荐/规划子 Agent（不挂 checkpointer，由父图统一保存状态）。"""
    template = PLAN_SYSTEM if kind == "plan" else RECOMMEND_SYSTEM
    prompt = template.format(city=city or "未确定")
    if not get_mcp_tools():
        prompt += "\n注意：实时工具当前不可用，涉及实时信息时直接说明无法查询，不要编造。"

    return create_agent(model=model, tools=tools or [], system_prompt=prompt)
