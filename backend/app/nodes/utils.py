"""节点通用工具：MCP 结果解析、工具查找、距离/日期计算、并发取详情"""

import asyncio
import math
from datetime import datetime, timedelta
from typing import List


def _extract_text(result) -> str:
    """从MCP工具返回结果中提取文本内容"""
    text_content = ""
    if isinstance(result, list):
        for block in result:
            if isinstance(block, dict) and block.get("type") == "text":
                text_content += block["text"]
    elif hasattr(result, "content"):
        text_content = result.content
    return text_content


def get_tool(tools, name: str):
    """按名称从工具列表中查找，找不到返回 None"""
    return next((t for t in tools if t.name == name), None)


def haversine_km(lon1, lat1, lon2, lat2) -> float:
    """两经纬度间大圆距离（公里）"""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def build_date_list(start_date: str, travel_days: int) -> List[str]:
    """按 start_date 顺序推算每日日期；解析失败则回退为仅 start_date"""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        return [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(travel_days)]
    except (ValueError, KeyError):
        return [start_date]


async def fetch_details(ids, detail_tool, *, concurrency, retries, retry_delay, logger) -> List[str]:
    """并发调用详情工具获取文本，失败重试，最终过滤空返回。

    返回非空文本列表（顺序与输入 ids 一致，已剔除 None）。
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(pid: str):
        async with semaphore:
            text = None
            for attempt in range(retries):
                result = await detail_tool.ainvoke({"id": pid})
                text = _extract_text(result)
                if text and not text.startswith("Error"):
                    return text
                if attempt < retries - 1:
                    await asyncio.sleep(retry_delay)
            logger.warning("详情获取失败: %s %s", pid, (text[:80] if text else "空返回"))
            return None

    texts = await asyncio.gather(*[fetch_one(pid) for pid in ids])
    return [t for t in texts if t is not None]
