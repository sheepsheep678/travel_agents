"""行程规划业务：请求校验、状态构建、Agent 调用、事件流与记录持久化。"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agent.graph import get_travel_plan_agent
from backend.app.agent.state import initial_state
from backend.app.core.database import get_session_factory
from backend.app.core.exceptions import BadRequestError
from backend.app.core.logging import get_logger
from backend.app.modules.sessions.service import SessionService
from backend.app.modules.trip.models import TripPlanRecord
from backend.app.modules.trip.repository import TripRepository
from backend.app.modules.trip.schemas import TripPlanResponse, TripRequest

logger = get_logger(__name__)


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
            await self._set_status(record.id, "failed", error=str(exc))
            logger.exception("旅行规划执行失败", record_id=record.id)
            return TripPlanResponse(
                success=False,
                message=f"旅行规划执行失败: {exc}",
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
