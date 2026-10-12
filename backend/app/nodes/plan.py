import json
import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from backend.app.models.response import Budget, DayPlan, ErrorResponse, Meal, TripPlan, WeatherInfo
from backend.app.state import PlannerState
from backend.app.prompts import PLAN_SYSTEM, PLAN_RETRY_MESSAGES, build_plan_prompt
from backend.app.nodes.utils import build_date_list

logger = logging.getLogger(__name__)


class DayRoute(BaseModel):
    start_name: str = Field(..., description="当日路线起点名称(酒店名或景点名)")
    end_name: str = Field(..., description="当日路线终点名称(景点名)")


class DayPlanBrief(BaseModel):
    day_index: int = Field(..., description="第几天(从0开始)")
    description: str = Field(..., description="当日行程描述")
    transportation: str = Field(..., description="交通方式")
    accommodation: str = Field(..., description="住宿")
    hotel_name: str = Field(..., description="当日酒店名，从候选酒店中逐字选择")
    attraction_names: List[str] = Field(..., description="当日景点名，按游览顺序，从候选景点中逐字选择")
    meals: List[Meal] = Field(default=[], description="餐饮列表")


class PlannerOutput(BaseModel):
    days: List[DayPlanBrief]
    day_routes: List[DayRoute]
    overall_suggestions: str
    budget: Optional[Budget] = None


def _plan_invalid(p: PlannerOutput) -> bool:
    """days/routes 为空，或存在某天未选任何景点 → 需重试"""
    if not p.days or not p.day_routes:
        return True
    return any(not d.attraction_names for d in p.days)


# 规划节点：汇总全部数据，LLM生成完整旅行计划及每日路线起终点
async def plan_node(state: PlannerState, llm, tools) -> dict:
    attractions = state.get("attractions_result", [])
    hotels = state.get("hotel_result", [])
    weather_list = state.get("weather_result", [])
    rag_result = state.get("rag_result", "")

    # 确定性推算每日日期
    travel_days = state.get("travel_days") or 1
    date_list = build_date_list(state["start_date"], travel_days)

    # 只给LLM精简信息(名称/类别/时长/价格)，坐标、地址、描述、图片等详情后续从state按名称回填
    attractions_brief = [
        {"name": a.name, "category": a.category, "visit_duration": a.visit_duration,
         "ticket_price": a.ticket_price, "rating": a.rating}
        for a in attractions if a.location is not None
    ]
    hotels_brief = [
        {"name": h.name, "type": h.type, "rating": h.rating,
         "distance": h.distance, "estimated_cost": h.estimated_cost,
         "price_range": h.price_range}
        for h in hotels
    ]
    weather_brief = [w.model_dump() for w in weather_list]

    # 双源重复检查：既被工具搜到、又被知识库推荐的景点（最高优先级）
    tool_names = {a.name for a in attractions if a.location is not None}
    rag_names = {n.strip() for n in (state.get("rag_attraction_names") or set()) if n and n.strip()}
    overlap_names = tool_names & rag_names
    logger.info("[规划Agent] 双源重合景点: %s", overlap_names or "无")
    logger.info("[规划Agent] 全部候选名称(合并去重后): %s", state.get("attraction_names", set()))

    # 修订模式：上一版计划被评估节点打回时，注入历史计划与评估反馈
    history_plans = state.get("history_plan", [])
    eval_feedback = state.get("eval_feedback", "")
    revision_block = ""
    if history_plans and eval_feedback:
        last_plan = history_plans[-1]
        last_brief = [
            {"day_index": d.day_index,
             "attraction_names": [a.name for a in d.attractions],
             "hotel_name": d.hotel.name if d.hotel else ""}
            for d in last_plan.days
        ]
        revision_block = f"""
       【修订模式】上一版计划(第{len(history_plans)}版)未通过合理性评估，请针对以下反馈逐条修复后重新生成：
       评估反馈:
       {eval_feedback}

       上一版计划要点(仅供参考，避免重复同样问题，不要原样照搬):
       {json.dumps(last_brief, ensure_ascii=False)}
       """

    plan_prompt = build_plan_prompt(
        state, date_list, attractions_brief, hotels_brief, weather_brief,
        overlap_names, revision_block,
    )

    logger.info("[规划Agent] LLM生成旅行计划框架中...")
    structured_llm = llm.with_structured_output(PlannerOutput)
    result = await structured_llm.ainvoke([
        {"role": "system", "content": PLAN_SYSTEM},
        {"role": "user", "content": plan_prompt},
    ])

    # LLM 偶发返回空计划或空景点日(attraction_names=[])，额外重试最多 2 次
    for retry_msg in PLAN_RETRY_MESSAGES:
        if not _plan_invalid(result):
            break
        logger.info("[规划Agent] 存在空计划/空景点日，重试...")
        result = await structured_llm.ainvoke([
            {"role": "system", "content": retry_msg},
            {"role": "user", "content": plan_prompt},
        ])

    # 确定性重建完整计划：景点/酒店/天气/日期等具体信息全部从state按名称回填，LLM只提供计划框架
    attractions_by_name = {a.name: a for a in attractions if a.location is not None}
    hotels_by_name = {h.name: h for h in hotels}

    days = []
    for b in result.days:
        day_attractions = []
        for name in b.attraction_names:
            src = attractions_by_name.get(name)
            if src is None:
                logger.info("[规划Agent] 景点「%s」不在候选数据中，已跳过", name)
                continue
            day_attractions.append(src)
        hotel = hotels_by_name.get(b.hotel_name)
        if hotel is None and b.hotel_name:
            logger.info("[规划Agent] 酒店「%s」不在候选数据中，已置空", b.hotel_name)
        date = date_list[b.day_index] if 0 <= b.day_index < len(date_list) else date_list[0]
        days.append(DayPlan(
            date=date,
            day_index=b.day_index,
            description=b.description,
            transportation=b.transportation,
            accommodation=b.accommodation,
            hotel=hotel,
            attractions=day_attractions,
            meals=b.meals,
        ))

    # 兜底：重试后仍有空景点日 → 用候选景点确定性填充，保证前端不出现空景点。
    # 优先匹配当日 description 里提到的候选名称（与行程描述保持一致），再按评分兜底。
    used = {a.name for d in days for a in d.attractions}
    filled_days = 0
    for d in days:
        if d.attractions:
            continue
        desc = d.description or ""
        pool = [a for n, a in attractions_by_name.items()
                if a.name not in used and n and n in desc]
        if not pool:
            pool = sorted(
                (a for a in attractions_by_name.values() if a.name not in used),
                key=lambda a: (a.rating or 0), reverse=True,
            )
        if pool:
            pick = pool[0]
            used.add(pick.name)
            d.attractions.append(pick)
            filled_days += 1
            logger.info("[规划Agent] 第%d天景点为空，确定性回填「%s」", d.day_index, pick.name)
    if filled_days:
        logger.info("[规划Agent] 共确定性回填 %d 个空景点日", filled_days)

    if not days:
        logger.warning("[规划Agent] 重试后仍为空计划，放弃本次生成")
        return {"parse_error": [ErrorResponse(message="行程计划生成失败，请重试")], "final_plan": None}

    # 确定性回填天气：每天都有天气条目（预报覆盖则用预报，未覆盖则占位空卡）
    weather_by_date = {w.date: w for w in weather_list}
    final_weather = [weather_by_date.get(d, WeatherInfo(date=d)) for d in date_list]

    plan = TripPlan(
        city=state["city"],
        start_date=state["start_date"],
        end_date=state["end_date"],
        days=days,
        weather_info=final_weather,
        overall_suggestions=result.overall_suggestions,
        budget=result.budget,
    )

    logger.info("[规划Agent] 完成，共 %d 天行程，天气 %d 天", len(plan.days), len(final_weather))

    return {"final_plan": plan}
