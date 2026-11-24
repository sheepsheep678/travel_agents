"""行程规划业务：请求校验、状态构建、Agent 调用、事件流与记录持久化。"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date as date_cls
from datetime import datetime
from typing import Any, AsyncIterator, Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agent.graph import get_travel_plan_agent
from backend.app.agent.state import initial_state
from backend.app.core.database import get_session_factory
from backend.app.core.exceptions import BadRequestError, ExternalServiceError
from backend.app.core.llm_errors import format_llm_error
from backend.app.core.logging import get_logger
from backend.app.integrations.mcp import get_mcp_tool
from backend.app.modules.sessions.service import SessionService
from backend.app.modules.trip.models import TripPlanRecord
from backend.app.modules.trip.repository import TripRepository
from backend.app.modules.trip.schemas import (
    TrainSearchResponse,
    TrainSeatPrice,
    TrainTicket,
    TripPlanResponse,
    TripRequest,
)

logger = get_logger(__name__)

_TRAIN_FILTER_RE = re.compile(r"^[GDZTKOFS]{0,8}$")


def _clean_city_name(value: str) -> str:
    """12306 只认城市/车站名，「北京市」需要归一成「北京」。"""
    name = (value or "").strip()
    return name[:-1] if name.endswith("市") else name


def _tool_text(result: Any) -> str:
    """从 MCP 工具结果中提取纯文本（兼容 list[content] / ToolMessage / str）。"""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        parts = []
        for block in result:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _tool_text(content)
    return "" if result is None else str(result)


class TripService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = TripRepository(db)

    async def prepare(self, req: TripRequest) -> tuple[dict, dict, TripPlanRecord]:
        """校验会话归属、构建 state/config，并写入一条 running 记录。"""
        state = initial_state()
        state.update(
            {
                "city": req.city,
                "user_id": req.user_id or "",
                "session_id": req.session_id or "",
                "start_date": req.start_date,
                "end_date": req.end_date,
                "travel_days": req.travel_days,
                "transportation": req.transportation,
                "accommodation": req.accommodation,
                "preferences": req.preferences or [],
                "free_text_input": req.free_text_input or "",
            }
        )

        session_service = SessionService(self.db)
        if req.user_id:
            # 保证 trip_plans.user_id 的外键有效（无 session 时也要先建用户）
            await session_service.ensure_user(req.user_id)
        if req.session_id:
            if not req.user_id:
                raise BadRequestError("提供 session_id 时必须同时提供 user_id")
            await session_service.assert_session(req.session_id, req.user_id)

        # 每次规划使用独立 thread，避免同一会话内多次规划把增量 reducer 的旧 state 叠加；
        # checkpoint 仍按 thread 持久化到 PostgreSQL。
        thread_id = f"{req.session_id or req.user_id or 'anon'}:{uuid4().hex}"
        record = await self.repo.create(
            user_id=req.user_id or None,
            session_id=req.session_id or None,
            thread_id=thread_id,
            request=req.model_dump(mode="json"),
        )
        await self.repo.commit()

        config = {"configurable": {"thread_id": thread_id}}
        return state, config, record

    async def _set_status(
        self,
        record_id: str,
        status: str,
        *,
        plan: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        """用独立 session 更新记录状态，避免流式响应取消后请求 session 失效。"""
        try:
            factory = get_session_factory()
            async with factory() as db:
                repo = TripRepository(db)
                record = await repo.get(record_id)
                if record is None:
                    return
                await repo.update_status(record, status=status, plan=plan, error=error)
                await repo.commit()
        except Exception:
            logger.exception("更新行程记录状态失败", record_id=record_id, status=status)

    async def generate(self, req: TripRequest) -> TripPlanResponse:
        state, config, record = await self.prepare(req)
        logger.info(
            "收到旅行规划请求",
            city=req.city,
            start_date=req.start_date,
            end_date=req.end_date,
            travel_days=req.travel_days,
            preferences=req.preferences,
            record_id=record.id,
        )

        agent = get_travel_plan_agent()
        try:
            result = await agent.ainvoke(state, config=config)
        except Exception as exc:
            message = format_llm_error(exc)
            await self._set_status(record.id, "failed", error=message)
            logger.exception("旅行规划执行失败", record_id=record.id)
            return TripPlanResponse(
                success=False,
                message=message,
                data=None,
            )

        final_plan = result.get("final_plan")
        if final_plan is None:
            errors = result.get("parse_error", []) or []
            msg = "；".join(
                e.message for e in errors if e and getattr(e, "message", None)
            )
            msg = msg or "未生成旅行计划，请稍后重试"
            await self._set_status(record.id, "failed", error=msg)
            logger.error("旅行规划未生成计划", message=msg, record_id=record.id)
            return TripPlanResponse(success=False, message=msg, data=None)

        plan_payload = final_plan.model_dump(mode="json")
        await self._set_status(record.id, "success", plan=plan_payload)
        logger.info(
            "旅行规划完成",
            city=final_plan.city,
            days=len(final_plan.days),
            record_id=record.id,
        )
        return TripPlanResponse(success=True, message="生成成功", data=final_plan)

    async def search_trains(
        self,
        *,
        from_city: str,
        to_city: str,
        date: str,
        filter_flags: str = "",
    ) -> TrainSearchResponse:
        """调用 12306 MCP 查询车次，并把原始 JSON 票面数据映射成稳定响应。"""
        from_city = _clean_city_name(from_city)
        to_city = _clean_city_name(to_city)
        filter_flags = (filter_flags or "").strip().upper()
        if not from_city or not to_city:
            raise BadRequestError("出发城市和到达城市不能为空")
        if not _TRAIN_FILTER_RE.fullmatch(filter_flags):
            raise BadRequestError("车次筛选只支持 G/D/Z/T/K/O/F/S 组合")

        try:
            parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            raise BadRequestError("日期格式应为 YYYY-MM-DD")
        if parsed_date < date_cls.today():
            raise BadRequestError("查询日期不能早于今天")

        tool = get_mcp_tool("get-tickets")
        if tool is None:
            raise ExternalServiceError("12306 车次服务未就绪，请稍后重试")

        try:
            result = await tool.ainvoke(
                {
                    "date": date,
                    "fromStation": from_city,
                    "toStation": to_city,
                    "trainFilterFlags": filter_flags,
                    "sortFlag": "startTime",
                    "limitedNum": 20,
                    "format": "json",
                }
            )
        except Exception as exc:
            logger.warning("12306 车次查询失败", from_city=from_city, to_city=to_city, error=str(exc))
            raise ExternalServiceError(f"12306 查询失败：{exc}")

        text = _tool_text(result).strip()
        if not text:
            raise ExternalServiceError("12306 未返回车次数据")
        if text.startswith("Error:"):
            raise ExternalServiceError(text)
        if text.startswith("没有查询到相关车次"):
            return TrainSearchResponse(
                success=True,
                message=text,
                from_city=from_city,
                to_city=to_city,
                date=date,
                tickets=[],
            )

        try:
            raw_tickets = json.loads(text)
        except (TypeError, ValueError):
            logger.warning("12306 返回内容不是 JSON", preview=text[:200])
            raise ExternalServiceError("12306 返回格式异常，请稍后重试")
        if not isinstance(raw_tickets, list):
            raise ExternalServiceError("12306 返回格式异常，请稍后重试")

        tickets: list[TrainTicket] = []
        for raw in raw_tickets[:20]:
            if not isinstance(raw, dict):
                continue
            prices = []
            for price in raw.get("prices") or []:
                if not isinstance(price, dict):
                    continue
                prices.append(
                    TrainSeatPrice(
                        seat_name=str(price.get("seat_name") or ""),
                        short=str(price.get("short") or ""),
                        num=price.get("num"),
                        price=price.get("price"),
                        discount=price.get("discount"),
                    )
                )
            tickets.append(
                TrainTicket(
                    train_no=str(raw.get("train_no") or ""),
                    train_code=str(raw.get("start_train_code") or ""),
                    start_date=str(raw.get("start_date") or ""),
                    arrive_date=str(raw.get("arrive_date") or ""),
                    start_time=str(raw.get("start_time") or ""),
                    arrive_time=str(raw.get("arrive_time") or ""),
                    duration=str(raw.get("lishi") or ""),
                    from_station=str(raw.get("from_station") or ""),
                    to_station=str(raw.get("to_station") or ""),
                    from_station_telecode=str(raw.get("from_station_telecode") or ""),
                    to_station_telecode=str(raw.get("to_station_telecode") or ""),
                    prices=prices,
                    flags=[str(flag) for flag in raw.get("dw_flag") or [] if flag],
                )
            )

        logger.info(
            "12306 车次查询完成",
            from_city=from_city,
            to_city=to_city,
            date=date,
            count=len(tickets),
        )
        return TrainSearchResponse(
            success=True,
            message="查询成功" if tickets else "没有查询到相关车次",
            from_city=from_city,
            to_city=to_city,
            date=date,
            tickets=tickets,
        )

    async def stream(
        self,
        req: TripRequest,
        state: dict,
        config: dict,
        record_id: str,
    ) -> AsyncIterator[dict]:
        logger.info(
            "收到旅行规划流式请求",
            city=req.city,
            start_date=req.start_date,
            end_date=req.end_date,
            travel_days=req.travel_days,
            preferences=req.preferences,
            record_id=record_id,
        )
        agent = get_travel_plan_agent()
        status_set = False
        try:
            async for event in agent.stream_events(state, config=config):
                if event.get("type") == "done":
                    status_set = True
                    if event.get("success"):
                        await self._set_status(record_id, "success", plan=event.get("data"))
                    else:
                        await self._set_status(
                            record_id, "failed", error=event.get("message")
                        )
                yield event
        except asyncio.CancelledError:
            if not status_set:
                try:
                    await asyncio.shield(
                        self._set_status(record_id, "cancelled", error="客户端断开连接")
                    )
                except Exception:
                    pass
            raise
        except Exception as exc:
            if not status_set:
                await self._set_status(record_id, "failed", error=str(exc))
            raise
        finally:
            if not status_set:
                await self._set_status(record_id, "cancelled", error="流式生成结束")
