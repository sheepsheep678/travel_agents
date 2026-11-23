"""对话工作流的状态契约与结构化输出模型。"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class IntentType(str, Enum):
    """意图类别。"""

    chitchat = "chitchat"
    recommend = "recommend"
    plan = "plan"
    human = "human"
    fallback = "fallback"
    dangerous = "dangerous"


class IntentResult(BaseModel):
    """意图识别节点的结构化输出。"""

    intent: IntentType = Field(description="本轮意图")
    reason: str = Field(default="", description="判断依据，20 字以内")
    risk_level: int = Field(default=0, ge=0, le=3, description="危险程度：0 正常，3 明确危险")


class SafetyVerdict(BaseModel):
    """安全围栏节点的结构化输出。"""

    is_safe: bool = Field(description="助手回复是否可以安全返回")
    reason: str = Field(default="", description="判定依据，20 字以内")


class ChatState(TypedDict, total=False):
    """父图状态：对话消息 + 路由上下文。"""

    messages: Annotated[list[AnyMessage], add_messages]
    city: str
    user_id: str
    previous_workflow: str
    activated_workflow: str
    intent_reason: str
    risk_level: int
    pending_reply: str
    chitchat_count: int


class ChitchatState(TypedDict, total=False):
    """闲聊子图状态：共享消息 + 独立的闲聊轮次计数。"""

    messages: Annotated[list[AnyMessage], add_messages]
    chitchat_count: int
    pending_reply: str


def initial_chat_state(city: str = "", user_id: str = "") -> ChatState:
    """构建对话初始状态。"""
    return {
        "messages": [],
        "city": city,
        "user_id": user_id,
        "previous_workflow": "",
        "activated_workflow": "",
        "intent_reason": "",
        "risk_level": 0,
        "pending_reply": "",
        "chitchat_count": 0,
    }


def last_human_text(messages: Optional[list[AnyMessage]]) -> str:
    """取最后一条用户消息的文本。"""
    for message in reversed(messages or []):
        if isinstance(message, HumanMessage):
            return _message_text(message)
    return ""


def last_ai_text(messages: Optional[list[AnyMessage]]) -> str:
    """取最后一条有正文的助手消息文本。"""
    for message in reversed(messages or []):
        if not isinstance(message, AIMessage):
            continue
        text = _message_text(message)
        if text.strip():
            return text
    return ""


def _message_text(message: AnyMessage) -> str:
    """把字符串或多模态内容块统一成文本。"""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""
