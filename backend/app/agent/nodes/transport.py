"""跨城交通节点：按出发城市与行程日期查询 12306 去程/返程车次。"""

from __future__ import annotations

import asyncio

from backend.app.agent.state import PlannerState
from backend.app.core.logging import get_logger
from backend.app.modules.trip.trains import clean_city_name, query_tickets

logger = get_logger(__name__)


async def transport_tool_node(state: PlannerState) -> dict:
    """查询去程与返程车次；未提供出发城市或工具不可用时静默返回空。"""
    origin = clean_city_name(state.get("origin_city") or "")
    dest = clean_city_name(state.get("city") or "")
    start = state.get("start_date") or ""
    end = state.get("end_date") or ""
    if not origin or not dest or origin == dest or not start:
        return {}

    tasks = [
        query_tickets(from_city=origin, to_city=dest, date=start, direction="outbound")
    ]
    # 单日行程不查返程，避免同一天重复请求
    if end and end != start:
        tasks.append(
            query_tickets(from_city=dest, to_city=origin, date=end, direction="return")
        )

    try:
        results = await asyncio.gather(*tasks)
    except Exception as exc:
        logger.warning("跨城车次查询失败，跳过交通信息", error=str(exc))
        return {}

    tickets = [ticket for group in results for ticket in group]
    logger.info(
        "跨城车次查询完成",
        origin=origin,
        destination=dest,
        outbound=len(results[0]) if results else 0,
        return_count=len(results[1]) if len(results) > 1 else 0,
    )
    return {"transport_result": tickets} if tickets else {}
