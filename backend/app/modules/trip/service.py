"""行程规划业务：请求校验、状态构建、Agent 调用、事件流与记录持久化。"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime
from typing import AsyncIterator, Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agent.graph import get_travel_plan_agent
from backend.app.agent.state import initial_state
from backend.app.core.config import settings
from backend.app.core.database import get_session_factory
from backend.app.core.exceptions import (
    BadRequestError,
    ExternalServiceError,
    NotFoundError,
)
from backend.app.core.llm_errors import format_llm_error
from backend.app.core.logging import get_logger
from backend.app.integrations.mcp import get_mcp_tool
from backend.app.modules.memory.service import MemoryService
from backend.app.modules.sessions.service import SessionService
from backend.app.modules.trip.models import TripPlanRecord
from backend.app.modules.trip.prefill import build_trip_prefill
from backend.app.modules.trip.repository import TripRepository
from backend.app.modules.trip.schemas import (
    TrainSearchResponse,
    TripPlanResponse,
    TripPrefillRequest,
    TripPrefillResponse,
    TripRequest,
)
from backend.app.modules.trip.trains import (
    clean_city_name,
    parse_tickets,
    tool_text,
)

logger = get_logger(__name__)

_TRAIN_FILTER_RE = re.compile(r"^[GDZTKOFS]{0,8}$")


@dataclass
class PlanRun:
    """一次行程图执行的实时事件缓冲，供首次订阅与断线重连共用。"""

    record_id: str
    events: list[dict] = field(default_factory=list)
    done: bool = False
    cancelled: bool = False
    task: Optional[asyncio.Task] = None
    created_at: float = field(default_factory=time.time)


_RUNS: dict[str, PlanRun] = {}
_RUN_TTL_SECONDS = 900


def _prune_runs() -> None:
    """清理已完成且超过 TTL 的运行缓冲，避免内存常驻。"""
    now = time.time()
    for key, run in list(_RUNS.items()):
        if run.done and now - run.created_at > _RUN_TTL_SECONDS:
            _RUNS.pop(key, None)


def _append_event(run: PlanRun, event: dict) -> None:
    """追加事件并写入递增序号，客户端据此断点续传。"""
    run.events.append({**event, "seq": len(run.events)})


_MEMORY_KIND_LABELS = {
    "preference": "偏好",
    "rule": "规则",
    "fact": "事实",
    "task_result": "历史任务",
    "workflow": "工作流",
    "lesson": "经验",
}


def _join_with_cap(parts: list[str], limit: int) -> str:
    """按顺序拼接区块并截断到上限，避免超长摘要挤爆提示词。"""
    kept: list[str] = []
    used = 0
    for part in parts:
        if not part:
            continue
        remaining = limit - used
        if remaining <= 0:
            break
        if len(part) > remaining:
            if remaining > 50:
                kept.append(part[:remaining])
            break
        kept.append(part)
        used += len(part) + 2
    return "\n\n".join(kept)


class TripService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = TripRepository(db)

    async def _build_memory_context(self, req: TripRequest) -> str:
        """把会话记忆与长期记忆拼成规划提示词区块；失败时静默降级。"""
        if not (settings.memory.enabled and req.user_id and req.session_id):
            return ""

        parts: list[str] = []
        memory_service = MemoryService(self.db)
        try:
            row = await memory_service.get_session_memory(
                req.session_id, req.user_id
            )
        except Exception as exc:
            logger.warning("读取会话记忆失败，规划不注入对话偏好", error=str(exc))
            row = None

        if row is not None:
            if row.summary:
                parts.append(f"【会话摘要】\n{row.summary}")

            facts = row.facts if isinstance(row.facts, dict) else {}
            confirmed = [
                str(item).strip()
                for item in (facts.get("confirmed") or [])
                if str(item).strip()
            ]
            if confirmed:
                parts.append(
                    "【已确认的对话偏好/事实】\n"
                    + "\n".join(f"- {item}" for item in confirmed[:20])
                )
            pending = [
                str(item).strip()
                for item in (facts.get("pending") or [])
                if str(item).strip()
            ]
            if pending:
                parts.append(
                    "【待确认信息（不要当成已确认事实）】\n"
                    + "\n".join(
                        f"- {item}" if "待确认" in item else f"- {item}（待确认）"
                        for item in pending[:10]
                    )
                )

            task_state = (
                row.task_state if isinstance(row.task_state, dict) else {}
            )
            task_fields = [
                (label, str(task_state.get(key) or "").strip())
                for key, label in (
                    ("city", "目的地"),
                    ("days", "天数"),
                    ("people", "同行人"),
                    ("budget", "预算"),
                    ("dates", "日期"),
                    ("notes", "其他约束"),
                )
                if str(task_state.get(key) or "").strip()
            ]
            if task_fields:
                parts.append(
                    "【对话任务状态】\n"
                    + "；".join(f"{label}：{value}" for label, value in task_fields)
                )

        if settings.memory.long_term_enabled:
            try:
                rows = await memory_service.list_memories(
                    req.user_id, city=req.city, limit=20
                )
            except Exception as exc:
                logger.warning("长期记忆召回失败，规划跳过该区块", error=str(exc))
                rows = []
            lines = [
                f"- [{_MEMORY_KIND_LABELS.get(str(item.get('kind') or ''), '记忆')}] "
                f"{' '.join(str(item.get('content') or '').split())}"
                for item in rows
                if str(item.get("status") or "confirmed") == "confirmed"
                and str(item.get("content") or "").strip()
            ]
            if lines:
                parts.append("【跨会话长期记忆】\n" + "\n".join(lines[:12]))

        if not parts:
            return ""
        return _join_with_cap(parts, settings.memory.context_max_chars)

    async def suggest_prefill(
        self, req: TripPrefillRequest
    ) -> TripPrefillResponse:
        """从对话会话提取快速开始表单预填。"""
        user_id = (req.user_id or "").strip()
        if not user_id:
            raise BadRequestError("user_id 不能为空")

        session_service = SessionService(self.db)
        await session_service.ensure_user(user_id)
        session = await session_service.assert_session(req.session_id, user_id)

        try:
            messages = await session_service.history.aget_messages(req.session_id)
        except Exception as exc:
            logger.warning("读取对话历史失败，预填只用记忆", error=str(exc))
            messages = []

        summary = ""
        facts: dict = {}
        task_state: dict = {}
        long_term: list[str] = []
        if settings.memory.enabled:
            memory_service = MemoryService(self.db)
            try:
                row = await memory_service.get_session_memory(
                    req.session_id, user_id
                )
                if row is not None:
                    summary = row.summary or ""
                    facts = row.facts if isinstance(row.facts, dict) else {}
                    task_state = (
                        row.task_state if isinstance(row.task_state, dict) else {}
                    )
            except Exception as exc:
                logger.warning("读取会话记忆失败，预填只用对话原文", error=str(exc))

            if settings.memory.long_term_enabled:
                try:
                    rows = await memory_service.list_memories(
                        user_id, city=session.city or "", limit=20
                    )
                except Exception as exc:
                    logger.warning("召回长期记忆失败，预填跳过", error=str(exc))
                    rows = []
                long_term = [
                    " ".join(str(item.get("content") or "").split())
                    for item in rows
                    if str(item.get("status") or "confirmed") == "confirmed"
                    and str(item.get("content") or "").strip()
                ][:12]

        prefill, source = await build_trip_prefill(
            session_city=session.city or "",
            summary=summary,
            facts=facts,
            task_state=task_state,
            long_term=long_term,
            messages=messages,
        )
        logger.info(
            "对话预填已生成",
            session_id=req.session_id,
            source=source,
            city=prefill.city,
            travel_days=prefill.travel_days,
            preferences=prefill.preferences,
        )
        return TripPrefillResponse(source=source, prefill=prefill)

    async def prepare(self, req: TripRequest) -> tuple[dict, dict, TripPlanRecord]:
        """校验会话归属、构建 state/config，并写入一条 running 记录。"""
        state = initial_state()
        # 表单字段是用户确认过的显式输入；memory_context 是对话里的补充材料，
        # 表单缺项时仍能保留「带父母 / 慢节奏 / 不吃辣」等偏好。
        memory_context = await self._build_memory_context(req)
        state.update(
            {
                "city": req.city,
                "origin_city": req.origin_city or "",
                "user_id": req.user_id or "",
                "session_id": req.session_id or "",
                "start_date": req.start_date,
                "end_date": req.end_date,
                "travel_days": req.travel_days,
                "transportation": req.transportation,
                "accommodation": req.accommodation,
                "preferences": req.preferences or [],
                "free_text_input": req.free_text_input or "",
                "memory_context": memory_context,
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
        from_city = clean_city_name(from_city)
        to_city = clean_city_name(to_city)
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

        text = tool_text(result).strip()
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
            tickets = parse_tickets(text, limit=20)
        except (TypeError, ValueError):
            logger.warning("12306 返回内容不是合法 JSON", preview=text[:200])
            raise ExternalServiceError("12306 返回格式异常，请稍后重试")

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
        after: int = -1,
    ) -> AsyncIterator[dict]:
        """首次订阅：启动后台图执行并回放/推送事件。"""
        run = self._start_run(req, state, config, record_id)
        async for event in self._subscribe(run, after):
            yield event

    def _start_run(
        self, req: TripRequest, state: dict, config: dict, record_id: str
    ) -> PlanRun:
        """创建（或复用）后台执行任务；客户端断开不影响图继续运行。"""
        _prune_runs()
        run = _RUNS.get(record_id)
        if run is not None:
            return run
        run = PlanRun(record_id=record_id)
        _RUNS[record_id] = run
        _append_event(run, {"type": "meta", "record_id": record_id})
        run.task = asyncio.create_task(self._execute(req, state, config, run))
        return run

    async def _execute(
        self, req: TripRequest, state: dict, config: dict, run: PlanRun
    ) -> None:
        """后台执行行程图：事件写入缓冲，完成/失败同步记录状态。"""
        logger.info(
            "开始旅行规划流式请求",
            city=req.city,
            start_date=req.start_date,
            end_date=req.end_date,
            travel_days=req.travel_days,
            record_id=run.record_id,
        )
        agent = get_travel_plan_agent()
        status_set = False
        try:
            async for event in agent.stream_events(state, config=config):
                if run.cancelled:
                    break
                _append_event(run, event)
                if event.get("type") == "done":
                    status_set = True
                    if event.get("success"):
                        await self._set_status(
                            run.record_id, "success", plan=event.get("data")
                        )
                    else:
                        await self._set_status(
                            run.record_id, "failed", error=event.get("message")
                        )
        except asyncio.CancelledError:
            run.cancelled = True
            raise
        except Exception as exc:
            logger.exception("旅行规划后台任务失败", record_id=run.record_id)
            if not status_set:
                await self._set_status(run.record_id, "failed", error=str(exc))
                _append_event(
                    run,
                    {
                        "type": "done",
                        "success": False,
                        "message": format_llm_error(exc),
                        "data": None,
                    },
                )
                status_set = True
        finally:
            # 先放开订阅者，状态落库失败也不能让前端永远等待
            run.done = True
            if not status_set:
                try:
                    await asyncio.shield(
                        self._set_status(
                            run.record_id,
                            "cancelled",
                            error="任务已取消" if run.cancelled else "任务意外中断",
                        )
                    )
                except BaseException:
                    pass

    async def _subscribe(self, run: PlanRun, after: int) -> AsyncIterator[dict]:
        """从 after 之后重放事件，并持续推送新事件直到任务结束。"""
        index = max(0, after + 1)
        while True:
            while index < len(run.events):
                yield run.events[index]
                index += 1
            if run.done:
                return
            await asyncio.sleep(0.05)

    async def assert_record(self, record_id: str, user_id: str = ""):
        """校验记录存在且属于该用户，供 SSE 响应开始前调用。"""
        record = await self.repo.get(record_id)
        if record is None or (user_id and record.user_id and record.user_id != user_id):
            raise NotFoundError("行程记录不存在")
        return record

    async def resume(
        self, record_id: str, user_id: str = "", after: int = -1
    ) -> AsyncIterator[dict]:
        """断线重连：按 record_id 校验归属后补发未收到的事件。"""
        record = await self.assert_record(record_id, user_id)
        run = _RUNS.get(record_id)
        if run is not None:
            async for event in self._subscribe(run, after):
                yield event
            return

        # 进程重启或缓冲已过期：用数据库里的终态补发 done
        seq = 0
        if after < 0:
            yield {"type": "meta", "record_id": record_id, "seq": seq}
            seq += 1
        if record.status == "success" and record.plan:
            yield {
                "type": "done",
                "success": True,
                "message": "生成成功",
                "data": record.plan,
                "seq": seq,
            }
        else:
            yield {
                "type": "done",
                "success": False,
                "message": record.error or "任务已中断，请重新规划",
                "data": None,
                "seq": seq,
            }

    async def cancel(self, record_id: str, user_id: str = "") -> None:
        """用户主动取消：终止后台任务并写入 cancelled 状态。"""
        await self.assert_record(record_id, user_id)
        run = _RUNS.get(record_id)
        if run is None or run.done:
            # 任务已完成时不覆盖 success/failed 状态
            return
        run.cancelled = True
        if run.task is not None and not run.task.done():
            run.task.cancel()
        await self._set_status(record_id, "cancelled", error="用户取消")
