"""行程规划路由。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from backend.app.core.deps import get_trip_service
from backend.app.modules.trip.schemas import TripPlanResponse, TripRequest
from backend.app.modules.trip.service import TripService

router = APIRouter(prefix="/trip", tags=["trip"])


@router.post("/plan", response_model=TripPlanResponse, summary="生成旅行计划")
async def generate_trip_plan(
    req: TripRequest,
    service: TripService = Depends(get_trip_service),
):
    """生成旅行计划（一次性返回完整计划，作为流式接口的兜底）。"""
    return await service.generate(req)


@router.post("/plan/stream", summary="生成旅行计划（SSE）")
async def generate_trip_plan_stream(
    req: TripRequest,
    service: TripService = Depends(get_trip_service),
):
    """生成旅行计划并实时推送节点进度。

    事件协议见 ``agent.graph.TravelPlanAgent.stream_events``；
    客户端断开时 sse-starlette 会取消生成器，从而停止图执行。
    """
    # 在响应开始前完成会话校验，校验失败会走全局异常处理器返回 JSON 错误
    state, config, record = await service.prepare(req)

    async def event_source():
        async for event in service.stream(req, state, config, record.id):
            yield {"data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(
        event_source(),
        ping=10,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
