"""对话工作流节点：意图识别、闲聊子图、推荐/规划、人工、兜底与安全围栏。"""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langgraph.config import get_stream_writer
from langgraph.graph import END
from langgraph.types import Command

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.modules.chat.workflow.prompts import (
    CHITCHAT_SYSTEM,
    INTENT_SYSTEM,
    SAFETY_SYSTEM,
    build_intent_user,
    build_safety_user,
)
from backend.app.modules.chat.workflow.state import (
    ChatState,
    ChitchatState,
    IntentResult,
    IntentType,
    last_ai_text,
    last_human_text,
)

logger = get_logger(__name__)

GREETING_REPLY = (
    "你好呀，我是旅迹智绘的旅行助手～可以帮你推荐目的地、规划行程、查询车次和天气。"
    "想从哪里开始？"
)
DANGER_REPLY = (
    "抱歉，这个请求我无法提供帮助。我只能协助旅行相关的问题，建议通过合法合规的渠道处理。"
)
FALLBACK_REPLY = (
    "我想先确认一下您的需求：您想去哪座城市、玩几天，或者想了解景点、美食、车次中的哪一类？"
)
HUMAN_REPLY = (
    "已为您登记转人工请求，客服会在工作时间内与您联系。"
    "您也可以先告诉我目的地和天数，我继续帮您整理行程。"
)
UNSAFE_REPLY = "抱歉，刚才的回复不符合使用规范，已撤回。请换个说法，我继续帮你处理旅行相关的问题。"
CHITCHAT_LIMIT_REPLY = (
    "我们已经聊了一会儿啦～回到旅行话题吧：告诉我目的地或想了解的内容，我来帮你安排。"
)
CHITCHAT_FALLBACK_REPLY = "抱歉，我刚刚没太理解，可以再说一次，或者告诉我你的旅行需求吗？"

_GREETING_RE = re.compile(
    r"^(你好|您好|hi|hello|嗨|哈喽|在吗|早上好|中午好|下午好|晚上好|早安|晚安)"
    r"[\s!！。，,~～?？]*$",
    re.IGNORECASE,
)
_PLAN_RE = re.compile(r"规划|行程|路线|安排|计划|几天|几日|怎么玩|玩几天")
_RECOMMEND_RE = re.compile(
    r"推荐|攻略|景点|美食|好吃|好玩|酒店|民宿|门票|天气|车次|火车|机票|去哪|值得去"
)

_ROUTE = {
    IntentType.chitchat: "chitchat",
    IntentType.recommend: "recommend",
    IntentType.plan: "plan",
    IntentType.human: "human",
    IntentType.fallback: "fallback",
}


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def _new_id() -> str:
    """生成消息 ID，保证安全围栏能按 ID 撤回消息。"""
    return uuid.uuid4().hex


def _get_writer():
    """获取自定义流写入器；非流式运行时退化为空操作。"""
    try:
        return get_stream_writer()
    except Exception:
        return lambda _payload: None


def _emit(writer, text: str) -> None:
    """把一个文本片段推给 SSE。"""
    if text:
        writer({"type": "token", "delta": text})


def _chunk_text(chunk: Any) -> str:
    """提取模型流式片段中的文本。"""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block
            if isinstance(block, str)
            else str(block.get("text") or "")
            for block in content
            if isinstance(block, (str, dict))
        )
    return ""


def _last_ai_message(messages: list[AnyMessage]) -> Optional[AIMessage]:
    """取最后一条助手消息对象。"""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


# ---------------------------------------------------------------------------
# 意图识别
# ---------------------------------------------------------------------------


async def intent_node(state: ChatState, *, intent_llm: Any) -> Command:
    """正则 → 小模型结构化识别 → Command 路由；识别失败走兜底。"""
    messages = list(state.get("messages") or [])
    query = last_human_text(messages).strip()
    previous = state.get("activated_workflow") or ""
    base = {"previous_workflow": previous, "risk_level": 0}

    if not query:
        return Command(
            goto="fallback",
            update={**base, "activated_workflow": "fallback", "intent_reason": "空输入"},
        )

    if _GREETING_RE.match(query):
        _emit(_get_writer(), GREETING_REPLY)
        return Command(
            goto="safety",
            update={
                **base,
                "messages": [AIMessage(content=GREETING_REPLY, id=_new_id())],
                "activated_workflow": "chitchat",
                "intent_reason": "寒暄正则命中",
            },
        )

    try:
        result = await intent_llm.ainvoke(
            [
                SystemMessage(content=INTENT_SYSTEM),
                HumanMessage(
                    content=build_intent_user(query, previous, last_ai_text(messages))
                ),
            ]
        )
    except Exception as exc:
        logger.warning("意图识别失败，走兜底", error=str(exc))
        return Command(
            goto="fallback",
            update={**base, "activated_workflow": "fallback", "intent_reason": "识别失败"},
        )

    if not isinstance(result, IntentResult):
        return Command(
            goto="fallback",
            update={**base, "activated_workflow": "fallback", "intent_reason": "结果非法"},
        )

    update = {
        "previous_workflow": previous,
        "activated_workflow": result.intent.value,
        "intent_reason": result.reason,
        "risk_level": result.risk_level,
    }
    # 回到业务工作流时重置闲聊轮次
    if result.intent != IntentType.chitchat:
        update["chitchat_count"] = 0
    logger.info(
        "意图识别完成",
        intent=result.intent.value,
        risk_level=result.risk_level,
        reason=result.reason,
    )

    # 危险请求直接结束，不再进入任何工作流
    if result.intent == IntentType.dangerous or result.risk_level >= 3:
        _emit(_get_writer(), DANGER_REPLY)
        update["activated_workflow"] = "dangerous"
        update["messages"] = [AIMessage(content=DANGER_REPLY, id=_new_id())]
        return Command(goto=END, update=update)

    return Command(goto=_ROUTE.get(result.intent, "fallback"), update=update)


# ---------------------------------------------------------------------------
# 闲聊子图
# ---------------------------------------------------------------------------


async def chitchat_guard_node(state: ChitchatState) -> Command:
    """闲聊中检测到业务意图时，直接跳回父图的推荐/规划工作流。"""
    query = last_human_text(list(state.get("messages") or []))
    if _PLAN_RE.search(query):
        return Command(
            graph=Command.PARENT,
            goto="plan",
            update={"previous_workflow": "chitchat", "activated_workflow": "plan"},
        )
    if _RECOMMEND_RE.search(query):
        return Command(
            graph=Command.PARENT,
            goto="recommend",
            update={"previous_workflow": "chitchat", "activated_workflow": "recommend"},
        )
    return Command(goto="chitchat_reply")


async def chitchat_reply_node(state: ChitchatState, *, llm: Any) -> dict:
    """累计闲聊轮次；未超限时由模型回复，超限后用固定模板。

    子图的 custom 流不会传回父图，因此回复先写入 ``pending_reply``，
    由父图的 emit_reply 节点统一推送。
    """
    count = int(state.get("chitchat_count") or 0) + 1

    if count > settings.chat.chitchat_max_rounds:
        return {
            "messages": [AIMessage(content=CHITCHAT_LIMIT_REPLY, id=_new_id())],
            "chitchat_count": count,
            "pending_reply": CHITCHAT_LIMIT_REPLY,
        }

    history = [SystemMessage(content=CHITCHAT_SYSTEM)] + list(
        state.get("messages") or []
    )[-settings.chat.max_history_messages:]
    parts: list[str] = []
    try:
        async for chunk in llm.astream(history):
            text = _chunk_text(chunk)
            if text:
                parts.append(text)
    except Exception as exc:
        logger.warning("闲聊回复生成失败", error=str(exc))

    reply = "".join(parts).strip() or CHITCHAT_FALLBACK_REPLY
    return {
        "messages": [AIMessage(content=reply, id=_new_id())],
        "chitchat_count": count,
        "pending_reply": reply,
    }


async def emit_reply_node(state: ChatState) -> dict:
    """把子图缓冲的回复推送给前端，并清空缓冲。"""
    _emit(_get_writer(), state.get("pending_reply") or "")
    return {"pending_reply": ""}


# ---------------------------------------------------------------------------
# 推荐 / 规划：绑定全部工具的子 Agent
# ---------------------------------------------------------------------------


async def _run_tool_agent(state: ChatState, agent: Any) -> dict:
    """运行工具子 Agent，边流 token 边收集最终回复。"""
    writer = _get_writer()
    history = list(state.get("messages") or [])[-settings.chat.max_history_messages:]
    final_state: dict = {}
    try:
        async for mode, payload in agent.astream(
            {"messages": history}, stream_mode=["messages", "values"]
        ):
            if mode == "messages":
                chunk, _meta = payload
                _emit(writer, _chunk_text(chunk))
            elif isinstance(payload, dict):
                final_state = payload
        reply = last_ai_text(final_state.get("messages"))
    except Exception as exc:
        logger.exception("工具子 Agent 执行失败", error=str(exc))
        reply = ""

    if not reply:
        reply = "抱歉，处理过程中出现问题，请稍后再试。"
        _emit(writer, reply)
    return {"messages": [AIMessage(content=reply, id=_new_id())]}


async def recommend_node(state: ChatState, *, agent: Any) -> dict:
    """目的地/景点/美食推荐工作流。"""
    return await _run_tool_agent(state, agent)


async def plan_node(state: ChatState, *, agent: Any) -> dict:
    """行程规划工作流。"""
    return await _run_tool_agent(state, agent)


# ---------------------------------------------------------------------------
# 人工 / 兜底 / 安全围栏
# ---------------------------------------------------------------------------


async def human_node(state: ChatState) -> dict:
    """人工工作流：当前只记录日志模拟转人工。"""
    logger.info("模拟转人工", user_id=state.get("user_id") or "")
    _emit(_get_writer(), HUMAN_REPLY)
    return {"messages": [AIMessage(content=HUMAN_REPLY, id=_new_id())]}


async def fallback_node(state: ChatState) -> dict:
    """信息不足或意图识别失败时反问用户。"""
    _emit(_get_writer(), FALLBACK_REPLY)
    return {"messages": [AIMessage(content=FALLBACK_REPLY, id=_new_id())]}


async def safety_node(state: ChatState, *, safety_llm: Any) -> dict:
    """安全围栏：用大模型复核助手回复，不安全时撤回并替换。"""
    if safety_llm is None:
        return {}

    messages = list(state.get("messages") or [])
    reply = last_ai_text(messages)
    if not reply:
        return {}

    try:
        verdict = await safety_llm.ainvoke(
            [
                SystemMessage(content=SAFETY_SYSTEM),
                HumanMessage(
                    content=build_safety_user(last_human_text(messages), reply)
                ),
            ]
        )
    except Exception as exc:
        logger.warning("安全围栏校验失败，放行", error=str(exc))
        return {}

    if getattr(verdict, "is_safe", True):
        return {}

    logger.warning("安全围栏拦截回复", reason=getattr(verdict, "reason", ""))
    _emit(_get_writer(), "\n\n" + UNSAFE_REPLY)
    last = _last_ai_message(messages)
    update: list[AnyMessage] = []
    if last is not None and getattr(last, "id", None):
        update.append(RemoveMessage(id=last.id))
    update.append(AIMessage(content=UNSAFE_REPLY, id=_new_id()))
    return {"messages": update}
