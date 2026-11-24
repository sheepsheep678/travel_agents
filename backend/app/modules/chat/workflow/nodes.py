"""对话工作流节点：意图识别、闲聊子图、推荐/规划、人工、兜底与安全围栏。"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any, Optional

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.config import get_config, get_stream_writer
from langgraph.graph import END
from langgraph.types import Command

from backend.app.core.config import settings
from backend.app.core.database import get_session_factory
from backend.app.core.logging import get_logger
from backend.app.integrations.cache import cache_get_json, cache_set_json, make_key
from backend.app.integrations.mcp import get_mcp_tool
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
from backend.app.modules.memory.service import (
    MemoryService,
    schedule_memory_save,
    window_messages,
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


def _skip_reply_cache() -> bool:
    """重新生成时由 ChatService 注入 skip_cache，绕过对话回复缓存。"""
    try:
        return bool(get_config().get("configurable", {}).get("skip_cache"))
    except Exception:
        return False


def _merge_chunks(chunks: list[Any]) -> Any:
    """把流式片段合并成一条完整消息。"""
    if not chunks:
        return None
    merged = chunks[0]
    for chunk in chunks[1:]:
        merged = merged + chunk
    return merged


def _fingerprint(messages: list[AnyMessage]) -> str:
    """把提示词上下文压缩成稳定指纹，用于回复缓存。"""
    rows = [
        [
            message.type,
            _chunk_text(message),
            [call.get("name") for call in (getattr(message, "tool_calls", None) or [])],
        ]
        for message in messages
    ]
    return json.dumps(rows, ensure_ascii=False, default=str)


def _sanitize_history(messages: list[AnyMessage]) -> list[AnyMessage]:
    """剔除未配对的工具调用，避免 Provider 因悬空 tool_calls 报错。"""
    cleaned: list[AnyMessage] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if isinstance(message, ToolMessage):
            index += 1
            continue
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            call_ids = {call.get("id") for call in message.tool_calls}
            end = index + 1
            answered: set = set()
            while end < len(messages) and isinstance(messages[end], ToolMessage):
                answered.add(messages[end].tool_call_id)
                end += 1
            if call_ids and call_ids.issubset(answered):
                cleaned.extend(messages[index:end])
                index = end
                continue
            index += 1
            continue
        cleaned.append(message)
        index += 1
    return cleaned


def _memory_block(state: ChatState | ChitchatState) -> str:
    """把摘要、事实、任务状态与长期记忆拼成一个精简系统区块。"""
    parts: list[str] = []
    summary = (state.get("memory_summary") or "").strip()
    if summary:
        parts.append(f"【会话记忆摘要】\n{summary}")

    facts = state.get("memory_facts") or {}
    if isinstance(facts, dict):
        confirmed = list(facts.get("confirmed") or [])[:12]
        pending = list(facts.get("pending") or [])[:8]
        if confirmed:
            parts.append(
                "【会话已确认事实】\n" + "\n".join(f"- {item}" for item in confirmed)
            )
        if pending:
            parts.append(
                "【待确认信息】\n" + "\n".join(f"- {item}" for item in pending)
            )

    task_state = state.get("memory_task_state") or {}
    if isinstance(task_state, dict):
        fields = [
            f"{label}：{task_state[key]}"
            for key, label in (
                ("city", "城市"),
                ("days", "天数"),
                ("people", "同行人"),
                ("budget", "预算"),
                ("dates", "日期"),
                ("notes", "其他约束"),
            )
            if str(task_state.get(key) or "").strip()
        ]
        if fields:
            parts.append("【当前任务状态】\n" + "；".join(fields))

    context = (state.get("memory_context") or "").strip()
    if context:
        parts.append(context)
    return "\n\n".join(parts)


def _memory_signature(state: ChatState | ChitchatState) -> str:
    """记忆上下文指纹，避免摘要变化后命中旧回复缓存。"""
    return json.dumps(
        {
            "summary": state.get("memory_summary") or "",
            "facts": state.get("memory_facts") or {},
            "task": state.get("memory_task_state") or {},
            "context": state.get("memory_context") or "",
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def build_working_messages(
    state: ChatState | ChitchatState, system_prompt: str
) -> list[AnyMessage]:
    """系统提示 + 记忆区块 + 最近 N 轮原文；窗口外的历史只以摘要出现。"""
    history = _sanitize_history(list(state.get("messages") or []))
    if settings.memory.enabled and settings.memory.window_rounds > 0:
        window = window_messages(history, settings.memory.window_rounds)
    else:
        # 记忆关闭时保留旧行为：按消息条数截断
        window = history[-settings.chat.max_history_messages:]
    window = _sanitize_history(window)
    system_parts = [system_prompt]
    memory = _memory_block(state)
    if memory:
        system_parts.append(memory)
    return [SystemMessage(content="\n\n".join(system_parts)), *window]


def _tool_text(result: Any) -> str:
    """把工具返回值统一成文本，并按配置截断。"""
    if isinstance(result, tuple):
        result = result[0] if result else ""
    if isinstance(result, str):
        text = result
    elif isinstance(result, list):
        text = "".join(
            block if isinstance(block, str) else str(block.get("text") or "")
            for block in result
            if isinstance(block, (str, dict))
        )
    elif hasattr(result, "content"):
        text = _chunk_text(result)
    else:
        text = str(result)
    limit = settings.chat.max_tool_result_chars
    if len(text) > limit:
        text = text[:limit] + "…"
    return text or "（工具无返回内容）"


# ---------------------------------------------------------------------------
# 意图识别
# ---------------------------------------------------------------------------


async def intent_node(state: ChatState, *, intent_llm: Any) -> Command:
    """正则 → 小模型结构化识别 → Command 路由；识别失败走兜底。"""
    messages = list(state.get("messages") or [])
    query = last_human_text(messages).strip()
    previous = state.get("activated_workflow") or ""
    # 每轮重置工具轮次，避免上一轮的计数影响本轮工具循环上限
    base = {"previous_workflow": previous, "risk_level": 0, "tool_round": 0}

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
                    content=build_intent_user(
                        query,
                        previous,
                        last_ai_text(messages),
                        _memory_block(state),
                    )
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

    messages = build_working_messages(state, CHITCHAT_SYSTEM)
    history = messages[1:]
    cache_key = make_key(
        "chat", "chitchat", _fingerprint(history), _memory_signature(state)
    )
    cached = None if _skip_reply_cache() else await cache_get_json(cache_key)
    if isinstance(cached, str) and cached:
        return {
            "messages": [AIMessage(content=cached, id=_new_id())],
            "chitchat_count": count,
            "pending_reply": cached,
        }

    parts: list[str] = []
    try:
        async for chunk in llm.astream(messages):
            text = _chunk_text(chunk)
            if text:
                parts.append(text)
    except Exception as exc:
        logger.warning("闲聊回复生成失败", error=str(exc))

    reply = "".join(parts).strip() or CHITCHAT_FALLBACK_REPLY
    await cache_set_json(cache_key, reply)
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
# 记忆：轮首加载 / 压缩，轮末异步写入
# ---------------------------------------------------------------------------


async def memory_load_node(state: ChatState) -> dict:
    """加载情景/长期记忆；窗口外历史达到阈值时做滚动摘要压缩。"""
    if not settings.memory.enabled:
        return {}

    user_id = (state.get("user_id") or "").strip()
    session_id = (state.get("session_id") or "").strip()
    if not user_id or not session_id:
        # 评测 / 未登录场景跳过数据库写入
        return {}

    messages = list(state.get("messages") or [])
    query = last_human_text(messages)
    city = state.get("city") or ""
    fallback = {
        "memory_summary": state.get("memory_summary") or "",
        "memory_facts": state.get("memory_facts") or {},
        "memory_task_state": state.get("memory_task_state") or {},
        "memory_context": state.get("memory_context") or "",
        "turn_count": int(state.get("turn_count") or 0) + 1,
    }

    try:
        factory = get_session_factory()
    except RuntimeError:
        return fallback

    try:
        async with factory() as db:
            service = MemoryService(db)
            row = await service.refresh_session_memory(
                session_id, user_id, messages, city
            )
            await db.commit()
            context = await service.build_context(user_id, city, query)
    except Exception as exc:
        logger.warning("记忆加载失败，沿用已有记忆", session_id=session_id, error=str(exc))
        return fallback

    return {
        "memory_summary": row.summary or "",
        "memory_facts": row.facts or {},
        "memory_task_state": row.task_state or {},
        "memory_context": context,
        "turn_count": int(row.turn_count or 0),
    }


async def memory_save_node(state: ChatState) -> dict:
    """轮末异步写入：显式指令、事实确认、定期批量、检索失败回写。"""
    schedule_memory_save(
        user_id=(state.get("user_id") or "").strip(),
        session_id=(state.get("session_id") or "").strip(),
        city=state.get("city") or "",
        turn_count=int(state.get("turn_count") or 0),
        messages=list(state.get("messages") or []),
        memory_facts=state.get("memory_facts") or {},
    )
    return {}


# ---------------------------------------------------------------------------
# 推荐 / 规划：LLM 绑定工具 → 工具节点 → 回到 LLM，直到给出最终回答
# ---------------------------------------------------------------------------


async def agent_llm_node(
    state: ChatState,
    *,
    llm: Any,
    plain_llm: Any,
    system_prompt: str,
    workflow: str,
) -> dict:
    """推荐/规划主回答：流式调用绑定工具的模型，产出回答或工具调用。"""
    writer = _get_writer()
    messages = build_working_messages(state, system_prompt)
    history = messages[1:]

    cache_key = make_key(
        "chat",
        workflow,
        state.get("city") or "",
        _fingerprint(history),
        _memory_signature(state),
    )
    cached = None if _skip_reply_cache() else await cache_get_json(cache_key)
    if isinstance(cached, str) and cached:
        logger.info("对话回复命中缓存", workflow=workflow)
        _emit(writer, cached)
        return {"messages": [AIMessage(content=cached, id=_new_id())]}

    # 达到工具轮次上限后不再绑定工具，并提示模型基于已有信息作答
    reached_limit = int(state.get("tool_round") or 0) >= settings.chat.max_tool_rounds
    model = plain_llm if reached_limit else llm
    if reached_limit:
        messages = [
            SystemMessage(
                content=(
                    f"{messages[0].content}\n"
                    "已达到工具调用次数上限，请直接基于已获得的信息作答；"
                    "缺失的实时信息如实说明无法查询，不要编造。"
                )
            ),
            *messages[1:],
        ]

    chunks: list[Any] = []
    try:
        async for chunk in model.astream(messages):
            text = _chunk_text(chunk)
            if text:
                _emit(writer, text)
            chunks.append(chunk)
    except Exception as exc:
        logger.exception("推荐/规划生成失败", workflow=workflow, error=str(exc))
        reply = "抱歉，处理过程中出现问题，请稍后再试。"
        _emit(writer, reply)
        return {"messages": [AIMessage(content=reply, id=_new_id())]}

    final = _merge_chunks(chunks)
    content = _chunk_text(final) if final is not None else ""
    tool_calls = list(getattr(final, "tool_calls", None) or []) if final is not None else []
    if not content.strip() and not tool_calls:
        content = "抱歉，我暂时没有生成内容，请再试一次。"
        _emit(writer, content)
    elif not tool_calls:
        await cache_set_json(cache_key, content)
    return {
        "messages": [AIMessage(content=content, tool_calls=tool_calls, id=_new_id())]
    }


async def _run_tool_call(tools: dict[str, Any], call: dict) -> ToolMessage:
    """执行单个工具调用：按工具名取工具，异常或缺工具时返回错误文本。"""
    name = str(call.get("name") or "")
    call_id = str(call.get("id") or _new_id())
    tool = tools.get(name) or get_mcp_tool(name)
    if tool is None:
        return ToolMessage(
            content=f"工具 {name} 当前不可用，请基于已有信息回答。",
            tool_call_id=call_id,
            name=name or "unknown",
        )
    try:
        result = await tool.ainvoke(call.get("args") or {})
    except Exception as exc:
        logger.warning("工具执行失败", tool=name, error=str(exc))
        return ToolMessage(
            content=f"工具 {name} 执行失败：{exc}", tool_call_id=call_id, name=name
        )
    return ToolMessage(content=_tool_text(result), tool_call_id=call_id, name=name)


async def agent_tools_node(state: ChatState, *, tools: dict[str, Any]) -> dict:
    """工具节点：按 tool_call 的工具名查找并执行，结果写回 ToolMessage。"""
    last = _last_ai_message(list(state.get("messages") or []))
    calls = list(getattr(last, "tool_calls", None) or []) if last is not None else []
    round_no = int(state.get("tool_round") or 0) + 1
    if not calls:
        return {"tool_round": round_no}

    results = await asyncio.gather(*(_run_tool_call(tools, call) for call in calls))
    return {"messages": list(results), "tool_round": round_no}


def route_after_agent(state: ChatState) -> str:
    """有工具调用 → 工具节点；否则结束到安全围栏。"""
    last = _last_ai_message(list(state.get("messages") or []))
    if last is not None and getattr(last, "tool_calls", None):
        return "agent_tools"
    return "safety"


def route_after_tools(state: ChatState) -> str:
    """工具执行后回到发起本轮的工作流。"""
    workflow = state.get("activated_workflow") or ""
    return workflow if workflow in ("recommend", "plan") else "safety"


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
