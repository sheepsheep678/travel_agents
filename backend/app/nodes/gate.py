import logging
from typing import Literal

from langgraph.constants import END

from backend.app.state import PlannerState

logger = logging.getLogger(__name__)


def is_plan_ready(state: PlannerState) -> bool:
    """数据齐备判定：各分支结果都存在且酒店轮次追上搜索轮次"""
    return (
        bool(state.get("attractions_result"))
        and bool(state.get("hotel_result"))
        and bool(state.get("weather_result"))
        and bool(state.get("rag_result"))
        and state.get("hotel_round", 0) >= state.get("search_round", 0)
    )


# 门控节点：汇聚三条并行分支，数据齐备才放行规划（替代 plan_node 内空跑守卫）
def plan_gate_node(state: PlannerState, llm=None, tools=None) -> dict:
    return {}


def plan_gate_router(state: PlannerState) -> Literal["plan_node", "__end__"]:
    """数据齐备 → plan_node；未齐备 → END（本轮等待，剩余分支完成后会再次触发门控）"""
    if is_plan_ready(state):
        logger.info("[门控] 上游数据齐备，放行规划节点")
        return "plan_node"
    logger.info("[门控] 上游数据未齐备，本轮等待（剩余分支完成后将再次触发）")
    return END


def rag_attraction_node_router(state: PlannerState) -> Literal["plan_gate_node", "attraction_tool_node"]:
    """判断 RAG 景点名称是否全部被搜索到的景点覆盖：
    有任一缺失 → attraction_tool_node 补搜；全部包含 → plan_gate_node 门控"""
    attraction_names = state.get("attraction_names") or set()
    rag_names = [n.strip() for n in (state.get("rag_attraction_names") or []) if n and n.strip()]

    # RAG 未提取到任何景点名（提取失败或知识库无景点）：无需补搜
    if not rag_names:
        logger.info("[RAG路由] RAG景点名为空，进入门控")
        return "plan_gate_node"

    missing = [n for n in rag_names if n not in attraction_names]
    if missing:
        logger.info("[RAG路由] %d 个RAG景点未被覆盖，跳转补搜: %s", len(missing), missing)
        return "attraction_tool_node"

    logger.info("[RAG路由] RAG景点已全部覆盖，进入门控")
    return "plan_gate_node"
