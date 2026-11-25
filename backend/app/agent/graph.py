"""LangGraph 行程规划图：构建、调用与 SSE 进度事件。"""

from __future__ import annotations

import asyncio
import time
from functools import partial
from typing import Optional

from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.types import RetryPolicy

from backend.app.agent.nodes import (
    attraction,
    evaluation,
    gate,
    hotel,
    plan,
    rag,
    transport,
    weather,
)
from backend.app.agent.constants import NODE_LABELS, NODE_RETRY_ATTEMPTS
from backend.app.agent.state import PlannerState, initial_state
from backend.app.core.database import get_checkpointer
from backend.app.core.llm_errors import format_llm_error
from backend.app.core.logging import get_logger
from backend.app.integrations.llm import get_fast_llm, get_llm
from backend.app.integrations.mcp import get_mcp_tools

logger = get_logger(__name__)

_agent_instance: Optional["TravelPlanAgent"] = None


class TravelPlanAgent:
    def __init__(self) -> None:
        self.llm = get_llm()
        # RAG / 评估 / 景点描述等轻量任务走快模型；未配置时与 self.llm 同一实例
        self.fast_llm = get_fast_llm()
        self.graph = None

    def _build_planner_graph(self):
        tools = get_mcp_tools("amap")
        workflow = StateGraph(PlannerState)

        workflow.add_node(
            "attraction_tool_node",
            partial(attraction.attraction_tool_node, llm=self.llm, tools=tools),
        )
        workflow.add_node(
            "attraction_enrich_node",
            partial(attraction.attraction_enrich_node, llm=self.fast_llm, tools=tools),
            retry_policy=RetryPolicy(max_attempts=NODE_RETRY_ATTEMPTS),
        )
        workflow.add_node(
            "rag_info_node",
            partial(rag.rag_info_node, llm=self.fast_llm, tools=tools),
            retry_policy=RetryPolicy(max_attempts=NODE_RETRY_ATTEMPTS),
        )
        workflow.add_node(
            "weather_tool_node",
            partial(weather.weather_tool_node, llm=self.llm, tools=tools),
        )
        workflow.add_node("transport_tool_node", transport.transport_tool_node)
        workflow.add_node(
            "hotel_tool_node",
            partial(hotel.hotel_tool_node, llm=self.llm, tools=tools),
        )
        workflow.add_node(
            "hotel_enrich_node",
            partial(hotel.hotel_enrich_node, llm=self.llm, tools=tools),
        )
        workflow.add_node(
            "plan_gate_node",
            partial(gate.plan_gate_node, llm=self.llm, tools=tools),
        )
        workflow.add_node(
            "plan_node",
            partial(plan.plan_node, llm=self.llm, tools=tools),
            retry_policy=RetryPolicy(max_attempts=NODE_RETRY_ATTEMPTS),
        )
        workflow.add_node(
            "evaluation_node",
            partial(evaluation.evaluation_node, llm=self.fast_llm, tools=tools),
            retry_policy=RetryPolicy(max_attempts=NODE_RETRY_ATTEMPTS),
        )

        workflow.add_edge(START, "attraction_tool_node")
        workflow.add_edge(START, "weather_tool_node")
        workflow.add_edge(START, "rag_info_node")
        workflow.add_edge(START, "transport_tool_node")
        workflow.add_conditional_edges(
            "rag_info_node",
            gate.rag_attraction_node_router,
            {"plan_gate_node": "plan_gate_node", "attraction_tool_node": "attraction_tool_node"},
        )
        workflow.add_edge("attraction_tool_node", "attraction_enrich_node")
        workflow.add_edge("attraction_enrich_node", "hotel_tool_node")
        workflow.add_edge("hotel_tool_node", "hotel_enrich_node")
        workflow.add_edge("hotel_enrich_node", "plan_gate_node")
        workflow.add_edge("weather_tool_node", "plan_gate_node")
        workflow.add_edge("transport_tool_node", "plan_gate_node")
        workflow.add_conditional_edges(
            "plan_gate_node",
            gate.plan_gate_router,
            {"plan_node": "plan_node", END: END},
        )
        workflow.add_edge("plan_node", "evaluation_node")
        workflow.add_conditional_edges(
            "evaluation_node",
            evaluation.evaluation_router,
            {"plan_node": "plan_node", "end": END},
        )

        checkpointer = get_checkpointer()
        self.graph = (
            workflow.compile(checkpointer=checkpointer)
            if checkpointer is not None
            else workflow.compile()
        )

    def _ensure_graph(self) -> None:
        if self.graph is None:
            self._build_planner_graph()

    async def ainvoke(self, state: PlannerState, config: Optional[dict] = None):
        self._ensure_graph()
        if config:
            return await self.graph.ainvoke(state, config=config)
        return await self.graph.ainvoke(state)

    async def stream_events(self, state: PlannerState, config: Optional[dict] = None):
        """基于 astream_events 的实时进度事件流（供 SSE 端点推送给前端）。

        事件协议（前端据此解析）：
            {"type": "node_start", "node": "...", "label": "..."}
            {"type": "node_end",   "node": "...", "payload": {...}}
            {"type": "node_error", "node": "...", "message": "...", "retry": true}
            {"type": "done",       "success": true/false, "message": "...", "data": TripPlan|None}
        """
        self._ensure_graph()

        final_plan = None
        parse_errors: list[str] = []
        started_at: dict[str, float] = {}
        stream = (
            self.graph.astream_events(state, config=config, version="v2")
            if config
            else self.graph.astream_events(state, version="v2")
        )
        try:
            async for ev in stream:
                name = ev.get("name") or ""
                etype = ev.get("event") or ""

                # 只保留图节点本身的 chain 事件，滤掉 LLM/tool/checkpoint 噪音
                if name not in NODE_LABELS or etype not in (
                    "on_chain_start",
                    "on_chain_end",
                    "on_chain_error",
                ):
                    continue

                if etype == "on_chain_start":
                    started_at[name] = time.perf_counter()
                    yield {"type": "node_start", "node": name, "label": NODE_LABELS[name]}
                elif etype == "on_chain_end":
                    output = (ev.get("data") or {}).get("output") or {}
                    for err in output.get("parse_error") or []:
                        msg = getattr(err, "message", None) or ""
                        if msg:
                            parse_errors.append(msg)
                    payload = self._node_end_payload(name, output)
                    t0 = started_at.pop(name, None)
                    if t0 is not None:
                        payload["duration_ms"] = round((time.perf_counter() - t0) * 1000)
                        logger.info("节点耗时", node=name, duration_ms=payload["duration_ms"])
                    yield {"type": "node_end", "node": name, "payload": payload}
                    # plan_node 经门控放行后仅执行一次；修订循环会再次激活，取最后非空计划
                    if name == "plan_node" and output.get("final_plan") is not None:
                        final_plan = output["final_plan"]
                else:  # on_chain_error：带重试策略的节点会再次启动
                    started_at.pop(name, None)
                    error = (ev.get("data") or {}).get("error") or "未知错误"
                    yield {
                        "type": "node_error",
                        "node": name,
                        "message": str(error)[:200],
                        "retry": True,
                    }
        except asyncio.CancelledError:
            logger.info("行程规划流被取消")
            raise
        except Exception as exc:
            logger.exception("流式图执行异常")
            yield {
                "type": "done",
                "success": False,
                "message": format_llm_error(exc),
                "data": None,
            }
            return

        if final_plan is not None:
            yield {
                "type": "done",
                "success": True,
                "message": "生成成功",
                "data": final_plan.model_dump(mode="json"),
            }
        else:
            msg = "；".join(parse_errors) or "未生成旅行计划，请稍后重试"
            yield {"type": "done", "success": False, "message": msg, "data": None}

    @staticmethod
    def _node_end_payload(name: str, output: dict) -> dict:
        """从节点返回值提取轻量进度信息（避免整包序列化 state）。"""
        if name == "attraction_enrich_node":
            return {"attraction_count": len(output.get("attractions_result") or [])}
        if name == "hotel_enrich_node":
            return {"hotel_count": len(output.get("hotel_result") or [])}
        if name == "weather_tool_node":
            return {"weather_count": len(output.get("weather_result") or [])}
        if name == "transport_tool_node":
            return {"transport_count": len(output.get("transport_result") or [])}
        if name == "attraction_tool_node":
            return {"new_names": len(output.get("attraction_names") or set())}
        if name == "rag_info_node":
            return {
                "hit_count": output.get("rag_hit_count") or 0,
                "retrieval": output.get("rag_backend") or "",
            }
        if name == "evaluation_node":
            return {"passed": output.get("eval_passed"), "round": output.get("eval_round")}
        return {}


def get_travel_plan_agent() -> TravelPlanAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = TravelPlanAgent()
    return _agent_instance


if __name__ == "__main__":
    from backend.app.core.logging import setup_logging
    from backend.app.integrations.mcp import ensure_initialized_sync

    setup_logging()
    ensure_initialized_sync()

    state = initial_state()
    state.update(
        {
            "city": "青岛",
            "start_date": "2026-8-20",
            "end_date": "2026-8-22",
            "travel_days": 3,
            "transportation": "自驾",
            "accommodation": "酒店",
            "preferences": ["风景", "啤酒", "崂山"],
            "free_text_input": "希望旅行氛围浪漫、轻松、惬意，慢节奏",
        }
    )

    agent = get_travel_plan_agent()
    result = asyncio.run(agent.ainvoke(state))
    print(f"result: {result}")
