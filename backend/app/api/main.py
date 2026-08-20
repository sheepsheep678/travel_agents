"""旅行助手后端 API 层

能力：
    POST /api/trip/plan         ->  TripRequest -> ainvoke -> TripPlanResponse（一次性）
    POST /api/trip/plan/stream  ->  TripRequest -> astream_events -> SSE 实时进度
健康检查：
    GET  /api/health
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.app.models.request import TripRequest
from backend.app.models.response import TripPlanResponse
from backend.app.nodes.tools.amap_mcp_servers import init_amap_mcp_async, close_amap_mcp
from backend.app.services.config import get_settings
from backend.app.services.travel_plan_agent import get_travel_plan_agent

logger = logging.getLogger("travel_plan_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：异步初始化高德 MCP 客户端（避免脚本写法的 asyncio.run 在事件循环内崩溃）
    logger.info("正在初始化高德 MCP 客户端...")
    await init_amap_mcp_async()
    logger.info("高德 MCP 客户端初始化完成")
    yield
    # 关闭
    await close_amap_mcp()
    logger.info("高德 MCP 客户端已关闭")


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

# CORS：允许前端开发服务器跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    app_name: str
    version: str
    mcp_ready: bool


def _build_planner_state(req: TripRequest) -> dict:
    """将 TripRequest 转换为 PlannerState 字典（字段与 travel_plan_agent.__main__ 示例一致）"""
    return {
        "city": req.city,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "travel_days": req.travel_days,
        "transportation": req.transportation,
        "accommodation": req.accommodation,
        "preferences": req.preferences or [],
        "free_text_input": req.free_text_input or "",
        # 以下字段由 Agent 各节点填充/消费，先置默认值
        "attraction_names": set(),
        "attractions_raw": "",
        "attractions_result": [],
        "search_round":0,
        "meal_result": [],
        "weather_result": [],
        "hotel_anchors": [],
        "hotels_raw": "",
        "hotel_result": [],
        "hotel_round": 0,
        "route_result": None,
        "day_route_locations": [],
        "final_plan": None,
        "parse_error": [],
        "rag_result": "",
        "rag_attraction_names": set(),
        "messages": [],
    }


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
async def health():
    """健康检查"""
    from backend.app.nodes.tools.amap_mcp_servers import _tools
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=settings.app_version,
        mcp_ready=len(_tools) > 0,
    )


@app.post("/api/trip/plan", response_model=TripPlanResponse, tags=["trip"])
async def generate_trip_plan(req: TripRequest):
    """生成旅行计划（唯一对外暴露的 Agent 能力）"""
    logger.info(
        "收到旅行规划请求: city=%s, %s~%s, %d 天, 偏好=%s",
        req.city, req.start_date, req.end_date, req.travel_days, req.preferences,
    )

    state = _build_planner_state(req)

    try:
        agent = get_travel_plan_agent()
        result = await agent.ainvoke(state)
    except Exception as e:
        logger.exception("旅行规划执行失败")
        return TripPlanResponse(success=False, message=f"旅行规划执行失败: {e}", data=None)

    final_plan = result.get("final_plan")
    if final_plan is None:
        # 上游某节点出错：把 parse_error 里的消息汇总返回
        errors = result.get("parse_error", []) or []
        msg = "；".join(e.message for e in errors if e and getattr(e, "message", None))
        logger.error("旅行规划未生成计划: %s", msg or "未知错误")
        return TripPlanResponse(success=False, message=msg or "未生成旅行计划，请稍后重试", data=None)

    logger.info("旅行规划完成: %s, 共 %d 天", final_plan.city, len(final_plan.days))
    return TripPlanResponse(success=True, message="生成成功", data=final_plan)


@app.post("/api/trip/plan/stream", tags=["trip"])
async def generate_trip_plan_stream(req: TripRequest, request: Request):
    """生成旅行计划（SSE 流式，实时推送各节点执行进度）

    事件协议见 travel_plan_agent.stream_events 的 docstring。
    """
    logger.info(
        "收到旅行规划流式请求: city=%s, %s~%s, %d 天, 偏好=%s",
        req.city, req.start_date, req.end_date, req.travel_days, req.preferences,
    )
    state = _build_planner_state(req)
    agent = get_travel_plan_agent()

    async def event_source():
        # 队列：feed 任务消费 astream_events，生成器负责心跳、断连检测与 SSE 格式化
        q: asyncio.Queue = asyncio.Queue(maxsize=100)

        async def feed():
            try:
                async for ev in agent.stream_events(state):
                    await q.put(ev)
            except Exception as e:
                logger.exception("流式事件源异常")
                await q.put({"type": "done", "success": False,
                             "message": f"旅行规划执行失败: {e}", "data": None})
            finally:
                await q.put(None)  # 结束标记

        feed_task = asyncio.create_task(feed())
        try:
            while True:
                # 客户端断开检测：is_disconnected 为非阻塞轮询，
                # 只有 uvicorn 收到断连并置位后才返回 True
                if await request.is_disconnected():
                    logger.info("客户端断开连接，取消图执行")
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=10)
                except asyncio.TimeoutError:
                    # 空档心跳：节点内 LLM/MCP 调用可能长时间无事件，
                    # 发 SSE 注释帧保持连接存活，绕过代理/网关的空闲超时
                    yield ": ping\n\n"
                    continue
                if ev is None:
                    break
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:
            # 客户端中途断开时取消图执行（取消 feed 任务会连带取消 graph.astream_events）
            feed_task.cancel()
            logger.info("SSE 流结束")

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.app.api.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
