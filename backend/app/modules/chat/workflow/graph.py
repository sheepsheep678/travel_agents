"""对话工作流图：START → 意图识别 → 五类工作流 → 安全围栏 → END。"""

from __future__ import annotations

from functools import partial
from typing import Any, Optional

from langgraph.graph import END, START, StateGraph

from backend.app.core.config import settings
from backend.app.core.database import get_checkpointer
from backend.app.integrations.llm import get_fast_llm, get_llm
from backend.app.modules.chat.workflow import nodes
from backend.app.modules.chat.workflow.state import (
    ChatState,
    ChitchatState,
    IntentResult,
    SafetyVerdict,
)
from backend.app.modules.chat.workflow.tools import (
    build_agent_llm,
    build_tool_map,
    collect_tools,
)

_SIMPLE_NODES = ("human", "fallback")


def _build_chitchat_graph(fast_llm: Any):
    """闲聊子图：业务意图守卫 → 模型回复；轮次计数随父图状态往返。"""
    graph = StateGraph(ChitchatState)
    graph.add_node("chitchat_guard", nodes.chitchat_guard_node)
    graph.add_node("chitchat_reply", partial(nodes.chitchat_reply_node, llm=fast_llm))
    graph.add_edge(START, "chitchat_guard")
    graph.add_edge("chitchat_reply", END)
    return graph.compile()


def build_chat_graph(
    city: str = "",
    user_id: str = "",
    *,
    tools: Optional[list] = None,
    checkpointer: Any = None,
):
    """构建并编译对话工作流；tools=None 时自动装配 MCP + 知识库工具。"""
    fast_llm = get_fast_llm()
    main_llm = get_llm()
    resolved_tools = collect_tools(city, user_id) if tools is None else list(tools)
    tool_map = build_tool_map(resolved_tools)
    saver = get_checkpointer() if checkpointer is None else checkpointer

    intent_llm = fast_llm.with_structured_output(IntentResult)
    safety_llm = (
        fast_llm.with_structured_output(SafetyVerdict)
        if settings.chat.safety_llm_enabled
        else None
    )
    recommend_llm, recommend_prompt = build_agent_llm(
        "recommend", city, main_llm, resolved_tools
    )
    plan_llm, plan_prompt = build_agent_llm("plan", city, main_llm, resolved_tools)

    graph = StateGraph(ChatState)
    graph.add_node("memory_load", nodes.memory_load_node)
    graph.add_node("memory_save", nodes.memory_save_node)
    graph.add_node("intent", partial(nodes.intent_node, intent_llm=intent_llm))
    graph.add_node("chitchat", _build_chitchat_graph(fast_llm))
    graph.add_node(
        "recommend",
        partial(
            nodes.agent_llm_node,
            llm=recommend_llm,
            plain_llm=main_llm,
            system_prompt=recommend_prompt,
            workflow="recommend",
        ),
    )
    graph.add_node(
        "plan",
        partial(
            nodes.agent_llm_node,
            llm=plan_llm,
            plain_llm=main_llm,
            system_prompt=plan_prompt,
            workflow="plan",
        ),
    )
    graph.add_node("agent_tools", partial(nodes.agent_tools_node, tools=tool_map))
    graph.add_node("human", nodes.human_node)
    graph.add_node("fallback", nodes.fallback_node)
    graph.add_node("emit_reply", nodes.emit_reply_node)
    graph.add_node("safety", partial(nodes.safety_node, safety_llm=safety_llm))

    graph.add_edge(START, "memory_load")
    graph.add_edge("memory_load", "intent")
    graph.add_edge("chitchat", "emit_reply")
    graph.add_edge("emit_reply", "safety")
    for name in ("recommend", "plan"):
        graph.add_conditional_edges(
            name,
            nodes.route_after_agent,
            {"agent_tools": "agent_tools", "safety": "safety"},
        )
    graph.add_conditional_edges(
        "agent_tools",
        nodes.route_after_tools,
        {"recommend": "recommend", "plan": "plan", "safety": "safety"},
    )
    for name in _SIMPLE_NODES:
        graph.add_edge(name, "safety")
    graph.add_edge("safety", "memory_save")
    graph.add_edge("memory_save", END)

    return graph.compile(checkpointer=saver) if saver else graph.compile()
