"""12306 车次查询与票面解析：HTTP 接口与行程图节点共用。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from backend.app.core.logging import get_logger
from backend.app.integrations.mcp import get_mcp_tool
from backend.app.modules.trip.schemas import TrainSeatPrice, TrainTicket

logger = get_logger(__name__)


def clean_city_name(value: str) -> str:
    """12306 只认城市/车站名，「北京市」需要归一成「北京」。"""
    name = (value or "").strip()
    return name[:-1] if name.endswith("市") else name


def tool_text(result: Any) -> str:
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
        return tool_text(content)
    return "" if result is None else str(result)


def normalize_date(value: str) -> str:
    """把日期归一成 12306 需要的 YYYY-MM-DD；无法解析时返回空串。"""
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def parse_tickets(text: str, *, limit: int = 20) -> list[TrainTicket]:
    """把 12306 的 JSON 文本解析成稳定的 TrainTicket 列表。"""
    raw_tickets = json.loads(text)
    if not isinstance(raw_tickets, list):
        raise ValueError("12306 返回格式异常")

    tickets: list[TrainTicket] = []
    for raw in raw_tickets[:limit]:
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
    return tickets


async def query_tickets(
    *,
    from_city: str,
    to_city: str,
    date: str,
    limit: int = 5,
    direction: str = "",
) -> list[TrainTicket]:
    """调用 12306 查询车次；不可用或失败时返回空列表，不抛异常。"""
    from_city = clean_city_name(from_city)
    to_city = clean_city_name(to_city)
    day = normalize_date(date)
    if not from_city or not to_city or not day or from_city == to_city:
        return []

    tool = get_mcp_tool("get-tickets")
    if tool is None:
        logger.warning("12306 工具未就绪，跳过跨城交通查询")
        return []

    try:
        result = await tool.ainvoke(
            {
                "date": day,
                "fromStation": from_city,
                "toStation": to_city,
                "trainFilterFlags": "",
                "sortFlag": "startTime",
                "limitedNum": max(limit, 10),
                "format": "json",
            }
        )
    except Exception as exc:
        logger.warning(
            "12306 跨城车次查询失败", from_city=from_city, to_city=to_city, error=str(exc)
        )
        return []

    text = tool_text(result).strip()
    if not text or text.startswith("Error:") or text.startswith("没有查询到相关车次"):
        return []
    try:
        tickets = parse_tickets(text, limit=limit)
    except (TypeError, ValueError) as exc:
        logger.warning("12306 跨城车次解析失败", error=str(exc), preview=text[:200])
        return []

    for ticket in tickets:
        ticket.direction = direction
    return tickets
