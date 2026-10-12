import logging
from typing import List, Literal

from pydantic import BaseModel, Field

from backend.app.state import PlannerState
from backend.app.constants import MAX_DAILY_MINUTES, MAX_EVAL_ROUNDS
from backend.app.prompts import EVAL_SYSTEM, build_eval_prompt

logger = logging.getLogger(__name__)


class EvalOutput(BaseModel):
    passed: bool = Field(..., description="计划是否通过合理性评估")
    score: int = Field(..., description="综合评分0-100")
    issues: List[str] = Field(default_factory=list, description="发现的具体问题")
    suggestions: List[str] = Field(default_factory=list, description="针对性改进建议")


def compute_hard_issues(plan, travel_days: int, hotels: list) -> List[str]:
    """确定性强校验（命中任一即判不通过）"""
    hard_issues = []
    if len(plan.days) != travel_days:
        hard_issues.append(f"行程天数为{len(plan.days)}天，与要求的{travel_days}天不符")
    for d in plan.days:
        if not d.attractions:
            hard_issues.append(f"第{d.day_index}天未安排任何景点")
        total_minutes = sum(a.visit_duration or 0 for a in d.attractions)
        if total_minutes > MAX_DAILY_MINUTES:
            hard_issues.append(f"第{d.day_index}天游览总时长{total_minutes}分钟，超过{MAX_DAILY_MINUTES}分钟上限")
        if hotels and d.hotel is None:
            hard_issues.append(f"第{d.day_index}天缺少酒店安排")
    return hard_issues


# 评估节点：确定性校验 + LLM评估，判断计划合理性
async def evaluation_node(state: PlannerState, llm, tools) -> dict:
    plan = state.get("final_plan")
    if plan is None:
        logger.info("[评估Agent] 无最终计划，跳过评估")
        return {}

    travel_days = state.get("travel_days") or 1
    hotels = state.get("hotel_result", [])

    # ---- 第一步：确定性强校验（命中任一即判不通过） ----
    hard_issues = compute_hard_issues(plan, travel_days, hotels)

    # ---- 第二步：LLM合理性评估 ----
    plan_brief = [
        {"day_index": d.day_index, "date": d.date,
         "attractions": [a.name for a in d.attractions],
         "hotel": d.hotel.name if d.hotel else "",
         "transportation": d.transportation,
         "description": d.description,
         "meals": [m.name for m in d.meals]}
        for d in plan.days
    ]
    eval_prompt = build_eval_prompt(state, travel_days, plan_brief, hard_issues)

    logger.info("[评估Agent] LLM评估行程合理性中...")
    structured_llm = llm.with_structured_output(EvalOutput)
    eval_result = await structured_llm.ainvoke([
        {"role": "system", "content": EVAL_SYSTEM},
        {"role": "user", "content": eval_prompt},
    ])

    # 硬性问题一票否决；无硬性问题时以LLM结论为准
    passed = (not hard_issues) and eval_result.passed
    feedback_items = hard_issues + eval_result.issues + [
        f"[建议] {s}" for s in eval_result.suggestions
    ]
    feedback = "\n".join(f"- {item}" for item in feedback_items)

    logger.info("[评估Agent] 第%d轮评估: score=%d, passed=%s, 问题数=%d",
                state.get("eval_round", 0) + 1, eval_result.score, passed, len(feedback_items))

    return {
        "eval_round": state.get("eval_round", 0) + 1,
        "eval_passed": passed,
        "eval_feedback": feedback,
        # 被驳回的计划归档为历史，供 plan_node 修订参考
        "history_plan": [] if passed else [plan],
    }


def evaluation_router(state: PlannerState) -> Literal["plan_node", "end"]:
    """评估通过/无计划/达到重规划上限 → 结束；否则打回 plan_node 修订"""
    if state.get("final_plan") is None:
        logger.info("[评估路由] 无最终计划，直接结束")
        return "end"
    if state.get("eval_passed"):
        logger.info("[评估路由] 计划通过评估，结束")
        return "end"
    if state.get("eval_round", 0) >= MAX_EVAL_ROUNDS:
        logger.info("[评估路由] 已达最大评估轮次(%d)，强制放行当前计划", MAX_EVAL_ROUNDS)
        return "end"
    logger.info("[评估路由] 计划未通过评估，打回 plan_node 修订")
    return "plan_node"
