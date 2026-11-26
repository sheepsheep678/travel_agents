"""对话 → 快速开始表单：偏好提取与确定性兜底。

预填只是让用户在表单里确认/修改，真正的防丢底牌是
``TripService.prepare()`` 注入的 ``memory_context``。
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date, timedelta
from typing import Sequence

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.core.logging import get_logger
from backend.app.integrations.llm import get_fast_llm
from backend.app.modules.sessions.schemas import MessageOut
from backend.app.modules.trip.schemas import TripPrefill

logger = get_logger(__name__)

_PREFILL_TIMEOUT = 20.0
_MAX_TRANSCRIPT_CHARS = 6000
_MAX_MESSAGE_CHARS = 800

_PREFERENCE_TAGS = [
    "历史文化", "自然风光", "美食", "休闲度假", "亲子", "购物", "夜生活",
    "博物馆", "海滩", "主题公园", "摄影", "户外徒步", "古镇", "温泉",
]

_TRANSPORT_KEYWORDS = ("公共交通", "自驾", "包车", "骑行", "高铁", "飞机", "火车")
_ACCOMMODATION_KEYWORDS = (
    "经济型酒店", "舒适型酒店", "豪华酒店", "民宿", "青年旅舍", "青旅", "酒店",
)

_CITY_NAMES = [
    "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安", "南京",
    "重庆", "青岛", "厦门", "三亚", "大理", "丽江", "苏州", "长沙", "昆明",
]

_CN_NUMBERS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

TRIP_PREFILL_SYSTEM = """你是旅行需求整理助手。请从对话记录和记忆中提取「快速开始」表单字段。

规则：
1. 只提取用户明确表达或已确认的信息，不要推测；没有依据的字段留空。
2. city 是目的地城市，origin_city 是出发城市，两者不要混淆。
3. 日期必须是 YYYY-MM-DD。用户说“下周末/国庆/三天后”等相对时间时，按给定今天日期换算；
   无法确定具体日期就留空。end_date 必须不早于 start_date。
4. travel_days 是行程天数，取值 1-30；无法确定填 0。
5. preferences 只能从这些标签中选：历史文化、自然风光、美食、休闲度假、亲子、购物、
   夜生活、博物馆、海滩、主题公园、摄影、户外徒步、古镇、温泉。最多 8 个。
6. free_text_input 汇总用户的额外约束（同行人、预算、节奏、忌口、必去/不去、特殊需求），
   保留用户原话关键点，不超过 200 字；不要重复 preferences 标签。
7. 会话城市、任务状态和长期记忆可作参考；对话里更新的说法优先。
8. notes 写一句提取说明或仍需在表单确认的信息，没有则留空。"""


def _parse_date(value: str) -> date | None:
    """解析常见日期写法，失败返回 None。"""
    text = (value or "").strip()
    if not text:
        return None
    text = (
        text.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("/", "-")
        .replace(".", "-")
    )
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if not match:
        return None
    try:
        return date(
            int(match.group(1)), int(match.group(2)), int(match.group(3))
        )
    except ValueError:
        return None


def _normalize_dates(
    start_raw: str, end_raw: str, days: int
) -> tuple[str, str, int]:
    """统一日期与天数：两者都有时以日期为准，最多 30 天。"""
    start = _parse_date(start_raw)
    end = _parse_date(end_raw)
    days = max(0, min(30, int(days or 0)))

    if start and end and end < start:
        start, end = end, start
    if start and end:
        span = (end - start).days + 1
        if span > 30:
            end = start + timedelta(days=29)
            span = 30
        days = span
    elif start and days > 0:
        end = start + timedelta(days=days - 1)
    elif end and days > 0:
        start = end - timedelta(days=days - 1)

    return (
        start.isoformat() if start else "",
        end.isoformat() if end else "",
        days,
    )


def _extract_days(text: str) -> int:
    """从“三天/5日”这类表达里取天数。"""
    match = re.search(r"(\d{1,2})\s*(?:天|日)", text or "")
    if match:
        value = int(match.group(1))
        return value if 1 <= value <= 30 else 0
    match = re.search(r"([一二两三四五六七八九十])\s*(?:天|日)", text or "")
    if match:
        return _CN_NUMBERS.get(match.group(1), 0)
    return 0


def _extract_dates(text: str) -> tuple[str, str]:
    """兜底提取显式 ISO 日期。"""
    matches = re.findall(r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}", text or "")
    start = matches[0] if matches else ""
    end = matches[1] if len(matches) > 1 else ""
    return start, end


def _first_city(text: str) -> str:
    for name in _CITY_NAMES:
        if name in (text or ""):
            return name
    return ""


def _guess_city(text: str) -> str:
    """优先识别目的地（去成都/北京三日游），避免把出发地当城市。"""
    for pattern in (
        r"(?:去|到|想去|准备去|打算去|飞往)\s*([一-龥]{2,6})",
        r"([一-龥]{2,6})\s*(?:旅游|旅行|游玩|玩|攻略|三日游|五日游)",
    ):
        for match in re.finditer(pattern, text or ""):
            candidate = match.group(1)
            for name in _CITY_NAMES:
                if name in candidate:
                    return name
    # 去掉“从北京出发”这类出发地短语后再找城市
    cleaned = re.sub(
        r"(?:从|由)[一-龥]{2,6}(?:出发|过去|飞|坐)", "", text or ""
    )
    return _first_city(cleaned)


def _extract_origin(text: str) -> str:
    """兜底识别“从北京出发 / 我是上海人”这类出发地。"""
    match = re.search(r"(?:从|由)\s*([一-龥]{2,6})\s*(?:出发|过去|飞|坐)", text or "")
    if match:
        return match.group(1)
    match = re.search(
        r"我(?:在|是)\s*([一-龥]{2,6}?)(?:人|居住|工作|生活)", text or ""
    )
    if match:
        return match.group(1)
    return ""


def _dedupe(items: Sequence[str], limit: int = 8) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = " ".join(str(item or "").split())
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _task_text(task_state: dict, key: str) -> str:
    if not isinstance(task_state, dict):
        return ""
    return str(task_state.get(key) or "").strip()


def heuristic_prefill(
    *,
    session_city: str,
    facts: dict,
    task_state: dict,
    messages: Sequence[MessageOut],
) -> TripPrefill:
    """不调用模型时的确定性预填，保证点击永远有结果。"""
    user_texts = [
        str(message.content or "")
        for message in messages
        if message.role == "user"
    ]
    all_text = "\n".join(str(message.content or "") for message in messages)
    last_user = (user_texts[-1] if user_texts else "").strip()

    confirmed = facts.get("confirmed") if isinstance(facts, dict) else None
    confirmed_text = "\n".join(str(item) for item in confirmed or [])

    city = (
        _task_text(task_state, "city")
        or session_city
        or _guess_city(all_text)
    )
    preferences = [tag for tag in _PREFERENCE_TAGS if tag in all_text]
    if not preferences:
        preferences = [tag for tag in _PREFERENCE_TAGS if tag in confirmed_text]

    start, end = _extract_dates(all_text)
    days = _extract_days(last_user) or _extract_days(all_text)
    if not days:
        days_text = _task_text(task_state, "days")
        digits = re.search(r"\d{1,2}", days_text)
        days = int(digits.group(0)) if digits else 0
    start, end, days = _normalize_dates(start, end, days)

    transportation = next(
        (word for word in _TRANSPORT_KEYWORDS if word in all_text), ""
    )
    accommodation = next(
        (word for word in _ACCOMMODATION_KEYWORDS if word in all_text), ""
    )

    return TripPrefill(
        city=city,
        origin_city=_extract_origin("\n".join(user_texts)),
        start_date=start,
        end_date=end,
        travel_days=days,
        transportation=transportation,
        accommodation=accommodation,
        preferences=preferences,
        free_text_input=last_user[:200],
    )


def _render_transcript(messages: Sequence[MessageOut]) -> str:
    """渲染最近对话，控制总长度。"""
    lines: list[str] = []
    used = 0
    for message in list(messages)[-20:]:
        content = " ".join(str(message.content or "").split())
        if not content:
            continue
        prefix = "用户" if message.role == "user" else "助手"
        line = f"{prefix}：{content[:_MAX_MESSAGE_CHARS]}"
        if used + len(line) > _MAX_TRANSCRIPT_CHARS:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)


def _build_user_prompt(
    *,
    today: date,
    session_city: str,
    summary: str,
    facts: dict,
    task_state: dict,
    long_term: Sequence[str],
    messages: Sequence[MessageOut],
) -> str:
    confirmed = facts.get("confirmed") if isinstance(facts, dict) else []
    pending = facts.get("pending") if isinstance(facts, dict) else []
    return "\n".join(
        [
            f"今天日期：{today.isoformat()}",
            f"会话城市：{session_city or '无'}",
            f"会话摘要：{(summary or '无')[:1500]}",
            "已确认事实："
            + ("；".join(str(item) for item in confirmed or []) or "无"),
            "待确认信息："
            + ("；".join(str(item) for item in pending or []) or "无"),
            "任务状态："
            + (json.dumps(task_state, ensure_ascii=False) if task_state else "无"),
            "跨会话长期记忆："
            + ("；".join(long_term) or "无"),
            "最近对话：",
            _render_transcript(messages) or "无",
        ]
    )


def _merge_prefill(llm_value: TripPrefill, fallback: TripPrefill) -> TripPrefill:
    """模型结果优先，空字段由兜底补足；日期与天数统一。"""
    start, end, days = _normalize_dates(
        llm_value.start_date or fallback.start_date,
        llm_value.end_date or fallback.end_date,
        llm_value.travel_days or fallback.travel_days,
    )
    return TripPrefill(
        city=(llm_value.city or fallback.city).strip(),
        origin_city=(llm_value.origin_city or fallback.origin_city).strip(),
        start_date=start,
        end_date=end,
        travel_days=days,
        transportation=(
            llm_value.transportation or fallback.transportation
        ).strip(),
        accommodation=(llm_value.accommodation or fallback.accommodation).strip(),
        preferences=_dedupe(
            list(llm_value.preferences or []) + list(fallback.preferences or [])
        ),
        free_text_input=(
            llm_value.free_text_input or fallback.free_text_input
        ).strip()[:200],
        notes=(llm_value.notes or fallback.notes).strip(),
    )


async def build_trip_prefill(
    *,
    session_city: str = "",
    summary: str = "",
    facts: dict | None = None,
    task_state: dict | None = None,
    long_term: Sequence[str] = (),
    messages: Sequence[MessageOut] = (),
) -> tuple[TripPrefill, str]:
    """生成表单预填：模型提取优先，任何失败都回落到确定性规则。"""
    facts = facts if isinstance(facts, dict) else {}
    task_state = task_state if isinstance(task_state, dict) else {}
    fallback = heuristic_prefill(
        session_city=session_city,
        facts=facts,
        task_state=task_state,
        messages=messages,
    )
    if not messages and not summary and not facts and not long_term:
        return fallback, "fallback"

    try:
        model = get_fast_llm().with_structured_output(TripPrefill)
        async with asyncio.timeout(_PREFILL_TIMEOUT):
            result = await model.ainvoke(
                [
                    SystemMessage(content=TRIP_PREFILL_SYSTEM),
                    HumanMessage(
                        content=_build_user_prompt(
                            today=date.today(),
                            session_city=session_city,
                            summary=summary,
                            facts=facts,
                            task_state=task_state,
                            long_term=long_term,
                            messages=messages,
                        )
                    ),
                ]
            )
    except Exception as exc:
        logger.warning("对话预填提取失败，使用兜底规则", error=str(exc))
        return fallback, "fallback"

    if isinstance(result, dict):
        try:
            result = TripPrefill(**result)
        except Exception:
            return fallback, "fallback"
    if not isinstance(result, TripPrefill):
        return fallback, "fallback"
    return _merge_prefill(result, fallback), "llm"
