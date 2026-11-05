"""节点通用工具：MCP 结果解析、工具查找、距离/日期计算、并发取详情"""

import asyncio
import difflib
import math
import re
import unicodedata
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


# 名称覆盖判断用的保守后缀白名单：只有「短名 + 常见景点后缀」才视为同一地点
_NAME_SUFFIXES = frozenset({
    "景区", "风景区", "旅游区", "游览区", "名胜区", "风景名胜区",
    "公园", "广场", "文化广场", "浴场", "海水浴场", "海滩",
    "码头", "博物馆", "纪念馆", "展览馆", "美术馆", "艺术馆",
    "旧址", "故居", "遗址", "园区", "苑", "园",
    "寺", "庙", "教堂", "塔", "楼", "阁", "亭", "桥", "岛", "山", "湾", "街", "路",
})

_PUNCT_RE = re.compile(r"[\s\-—_·•,，.。、;；:：()（）\[\]【】'\"“”‘’]")


def normalize_poi_name(name: str) -> str:
    """名称归一化：全角转半角、去空白/标点、小写"""
    s = unicodedata.normalize("NFKC", str(name or "")).strip().lower()
    return _PUNCT_RE.sub("", s)


def _is_covered_one(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True

    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 2 and short in long:
        if long.startswith(short):
            extra = long[len(short):]
        elif long.endswith(short):
            extra = long[:-len(short)]
        else:
            extra = long.replace(short, "", 1)
        if extra in _NAME_SUFFIXES:
            return True

    # 错别字/异写：长度接近且相似度足够高
    if min(len(a), len(b)) >= 4 and abs(len(a) - len(b)) <= 2:
        if difflib.SequenceMatcher(None, a, b).ratio() >= 0.9:
            return True
    return False


def is_name_covered(name: str, candidates) -> bool:
    """判断名称是否被候选名称覆盖（双向包含 + 保守后缀/相似度）"""
    a = normalize_poi_name(name)
    return any(_is_covered_one(a, normalize_poi_name(c)) for c in candidates if c)


def find_uncovered_names(rag_names, candidate_names, fuzzy: bool = True):
    """找出未被候选覆盖的名称；fuzzy=False 时退回到旧的精确匹配语义"""
    if not fuzzy:
        return [n for n in rag_names if n not in candidate_names]
    candidates = [c for c in (candidate_names or []) if c]
    return [n for n in (rag_names or []) if n and not is_name_covered(n, candidates)]


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
