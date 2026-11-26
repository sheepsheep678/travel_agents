"""行程规划路由。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sse_starlette.sse import EventSourceResponse

from backend.app.core.deps import get_trip_service
from backend.app.modules.trip.schemas import (
    TrainSearchResponse,
    TripCancelRequest,
    TripPlanResponse,
    TripPrefillRequest,
    TripPrefillResponse,
    TripRequest,
    TripResumeRequest,
)
from backend.app.modules.trip.service import TripService

router = APIRouter(prefix="/trip", tags=["trip"])


@router.post(
    "/prefill",
    response_model=TripPrefillResponse,
    summary="从对话会话提取行程表单预填",
)
async def suggest_trip_prefill(
    req: TripPrefillRequest,
    service: TripService = Depends(get_trip_service),
):
    """读取会话记忆 + 最近对话，用快模型结构化成快速开始表单字段。

    失败时回落到确定性规则，保证用户点击后总能进入预填表单。
    """
    return await service.suggest_prefill(req)


@router.post("/plan", response_model=TripPlanResponse, summary="生成旅行计划")
async def generate_trip_plan(
    req: TripRequest,
    service: TripService = Depends(get_trip_service),
):
    """生成旅行计划（一次性返回完整计划，作为流式接口的兜底）。"""
    return await service.generate(req)


@router.get("/trains", response_model=TrainSearchResponse, summary="查询 12306 车次")
async def search_trains(
    from_city: str = Query(..., min_length=1, description="出发城市"),
    to_city: str = Query(..., min_length=1, description="到达城市"),
    date: str = Query(..., min_length=10, max_length=10, description="出发日期 YYYY-MM-DD"),
    filter_flags: str = Query("", max_length=8, description="车次类型筛选：G/D/Z/T/K/O/F/S"),
    service: TripService = Depends(get_trip_service),
):
    """查询 12306 实时余票，供结果页车次票面轮播使用。"""
    return await service.search_trains(
        from_city=from_city,
        to_city=to_city,
        date=date,
        filter_flags=filter_flags,
    )


@router.post("/plan/stream", summary="生成旅行计划（SSE）")
async def generate_trip_plan_stream(
    req: TripRequest,
    service: TripService = Depends(get_trip_service),
):
    """生成旅行计划并实时推送节点进度。

    事件协议见 ``agent.graph.TravelPlanAgent.stream_events``；
    图在后台任务中执行，客户端断开只会停止订阅，不会中断规划；
    重连时调用 ``POST /trip/plan/resume`` 按 record_id 补发未收到的事件。
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


@router.post("/plan/resume", summary="断线续传行程进度（SSE）")
async def resume_trip_plan_stream(
    req: TripResumeRequest,
    service: TripService = Depends(get_trip_service),
):
    """按 record_id 重放未收到的事件；后台任务不会因客户端断开而停止。"""
    await service.assert_record(req.record_id, req.user_id or "")

    async def event_source():
        async for event in service.resume(
            req.record_id, req.user_id or "", req.after
        ):
            yield {"data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(
        event_source(),
        ping=10,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/plan/cancel", summary="取消行程规划")
async def cancel_trip_plan(
    req: TripCancelRequest,
    service: TripService = Depends(get_trip_service),
):
    """用户主动停止：终止后台图执行并记录 cancelled 状态。"""
    await service.cancel(req.record_id, req.user_id or "")
    return {"success": True, "message": "已取消"}
