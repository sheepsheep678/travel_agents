import asyncio
import logging
from functools import partial

from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.types import RetryPolicy

from backend.app.state import PlannerState, initial_state
from backend.app.constants import NODE_LABELS, NODE_RETRY_ATTEMPTS
from backend.app.nodes.llm import get_llm
from backend.app.nodes.tools.amap_mcp_servers import get_amap_mcp_client, get_amap_mcp_tools
from backend.app.nodes import attraction, hotel, weather, rag, plan, evaluation, gate
from backend.app.services.config import settings

logger = logging.getLogger(__name__)

_agent_instance = None


class TravelPlanAgent:
    def __init__(self):
        self.llm = get_llm()
        self.mcp_client = get_amap_mcp_client()
        self.mcp_tools = get_amap_mcp_tools()
        self.attraction_model = self.llm.bind_tools(self.mcp_tools)
        self.weather_model = self.llm.bind_tools(self.mcp_tools)
        self.hotel_model = self.llm.bind_tools(self.mcp_tools)
        self.planner_model = self.llm.bind_tools(self.mcp_tools)
        self.graph = None

    def _build_planner_graph(self):
        workflow = StateGraph(PlannerState)

        workflow.add_node("attraction_tool_node",
                          partial(attraction.attraction_tool_node, llm=self.llm, tools=self.mcp_tools))
        workflow.add_node("attraction_enrich_node",
                          partial(attraction.attraction_enrich_node, llm=self.llm, tools=self.mcp_tools),
                          retry_policy=RetryPolicy(max_attempts=NODE_RETRY_ATTEMPTS))
        workflow.add_node("rag_info_node",
                          partial(rag.rag_info_node, llm=self.llm, tools=self.mcp_tools),
                          retry_policy=RetryPolicy(max_attempts=NODE_RETRY_ATTEMPTS))
        workflow.add_node("weather_tool_node",
                          partial(weather.weather_tool_node, llm=self.llm, tools=self.mcp_tools))
        workflow.add_node("hotel_tool_node",
                          partial(hotel.hotel_tool_node, llm=self.llm, tools=self.mcp_tools))
        workflow.add_node("hotel_enrich_node",
                          partial(hotel.hotel_enrich_node, llm=self.llm, tools=self.mcp_tools))
        workflow.add_node("plan_gate_node",
                          partial(gate.plan_gate_node, llm=self.llm, tools=self.mcp_tools))
        workflow.add_node("plan_node",
                          partial(plan.plan_node, llm=self.llm, tools=self.mcp_tools),
                          retry_policy=RetryPolicy(max_attempts=NODE_RETRY_ATTEMPTS))
        workflow.add_node("evaluation_node",
                          partial(evaluation.evaluation_node, llm=self.llm, tools=self.mcp_tools),
                          retry_policy=RetryPolicy(max_attempts=NODE_RETRY_ATTEMPTS))

        workflow.add_edge(START, "attraction_tool_node")
        workflow.add_edge(START, "weather_tool_node")
        workflow.add_edge(START, "rag_info_node")
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

        self.graph = workflow.compile()

    async def ainvoke(self, state: PlannerState):
        if self.graph is None:
            self._build_planner_graph()
        return await self.graph.ainvoke(state)

    async def stream_events(self, state: PlannerState):
        """基于 astream_events 的实时进度事件流（供 SSE 端点推送给前端）

        事件协议（前端据此解析）：
            {"type": "node_start", "node": "...", "label": "..."}
            {"type": "node_end",   "node": "...", "payload": {...}}
            {"type": "node_error", "node": "...", "message": "...", "retry": true}
            {"type": "done",       "success": true/false, "message": "...", "data": TripPlan|None}
        """
        if self.graph is None:
            self._build_planner_graph()

        final_plan = None
        parse_errors = []
        try:
            async for ev in self.graph.astream_events(state, version="v2"):
                name = ev.get("name") or ""
                etype = ev.get("event") or ""

                # 只保留 7 个图节点本身的 chain 事件，滤掉 LLM/tool/checkpoint 噪音
                if name not in NODE_LABELS or etype not in (
                        "on_chain_start", "on_chain_end", "on_chain_error"):
                    continue

                if etype == "on_chain_start":
                    yield {"type": "node_start", "node": name, "label": NODE_LABELS[name]}
                elif etype == "on_chain_end":
                    output = (ev.get("data") or {}).get("output") or {}
                    # 汇总节点返回的错误信息（最终失败时提示用户）
                    for err in output.get("parse_error") or []:
                        msg = getattr(err, "message", None) or ""
                        if msg:
                            parse_errors.append(msg)
                    yield {"type": "node_end", "node": name,
                           "payload": self._node_end_payload(name, output)}
                    # plan_node 经门控放行后仅执行一次；修订循环会再次激活，取最后非空计划
                    if name == "plan_node" and output.get("final_plan") is not None:
                        final_plan = output["final_plan"]
                else:  # on_chain_error：带重试策略的节点会再次启动
                    error = (ev.get("data") or {}).get("error") or "未知错误"
                    yield {"type": "node_error", "node": name,
                           "message": str(error)[:200], "retry": True}
        except Exception as e:
            logger.error("[流式] 图执行异常: %s", e)
            yield {"type": "done", "success": False,
                   "message": f"旅行规划执行失败: {e}", "data": None}
            return

        if final_plan is not None:
            yield {"type": "done", "success": True, "message": "生成成功",
                   "data": final_plan.model_dump(mode="json")}
        else:
            msg = "；".join(parse_errors) or "未生成旅行计划，请稍后重试"
            yield {"type": "done", "success": False, "message": msg, "data": None}

    @staticmethod
    def _node_end_payload(name: str, output: dict) -> dict:
        """从节点返回值提取轻量进度信息（避免整包序列化 state）"""
        if name == "attraction_enrich_node":
            return {"attraction_count": len(output.get("attractions_result") or [])}
        if name == "hotel_enrich_node":
            return {"hotel_count": len(output.get("hotel_result") or [])}
        if name == "weather_tool_node":
            return {"weather_count": len(output.get("weather_result") or [])}
        if name == "attraction_tool_node":
            return {"new_names": len(output.get("attraction_names") or set())}
        if name == "evaluation_node":
            return {"passed": output.get("eval_passed"), "round": output.get("eval_round")}
        return {}


def get_travel_plan_agent() -> TravelPlanAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = TravelPlanAgent()
    return _agent_instance


if __name__ == "__main__":
    logging.basicConfig(level=settings.log_level)

    state = initial_state()
    state.update({
        "city": "青岛",
        "start_date": "2026-8-20",
        "end_date": "2026-8-22",
        "travel_days": 3,
        "transportation": "自驾",
        "accommodation": "酒店",
        "preferences": ["风景", "啤酒", "崂山"],
        "free_text_input": "希望旅行氛围浪漫、轻松、惬意，慢节奏",
    })

    agent = get_travel_plan_agent()
    result = asyncio.run(agent.ainvoke(state))
    print(f"result: {result}")
    print(f"result[attractions_result]: {result['attractions_result']}")
    print(f"result[weather_result]: {result['weather_result']}")
    print(f"result[hotel_anchors]: {result['hotel_anchors']}")
    print(f"result[hotel_result]: {result['hotel_result']}")
    print(f"result[final_plan]: {result['final_plan']}")
    print(f"result[parse_error]: {result['parse_error']}")
    print(f"result[rag_result]: {result['rag_result']}")
    print(f"[plan]:")
    print(f"总体建议: {result['final_plan'].overall_suggestions}")
    print(f"天气信息: {result['final_plan'].weather_info}")
    print(f"预算: {result['final_plan'].budget}")
    for day_plan in result['final_plan'].days:
        print(f"- 第{day_plan.day_index}天")
        print(f"  - 大概行程：{day_plan.description}")
        print(f"  - 交通方式：{day_plan.transportation}")
        print(f"  - 住宿：{day_plan.accommodation}")
        print(f"  - 推荐酒店：{day_plan.hotel}")
        print(f"  - 景点：{day_plan.attractions}")
        print(f"  - 餐饮：{day_plan.meals}")
