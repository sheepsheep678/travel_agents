"""记忆模块的内部结构化类型（摘要、事实抽取、长期记忆条目）。"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class MemoryKind(str, Enum):
    """长期记忆类别：语义记忆 + 程序记忆。"""

    preference = "preference"
    fact = "fact"
    rule = "rule"
    task_result = "task_result"
    workflow = "workflow"
    lesson = "lesson"
    gap = "gap"


class MemoryStatus(str, Enum):
    """长期记忆状态：只有 confirmed 会注入提示词。"""

    confirmed = "confirmed"
    pending = "pending"


class TaskState(BaseModel):
    """外置的任务状态：不依赖上下文窗口保存关键参数。"""

    city: str = Field(default="", description="目的地城市")
    days: str = Field(default="", description="行程天数")
    people: str = Field(default="", description="同行人数与关系")
    budget: str = Field(default="", description="预算范围")
    dates: str = Field(default="", description="出行日期")
    notes: str = Field(default="", description="其他任务约束")


class MemoryCompression(BaseModel):
    """窗口外历史的压缩结果。"""

    summary: str = Field(default="", description="历史对话摘要，只写事实")
    confirmed_facts: list[str] = Field(
        default_factory=list, description="已确认事实，每条一句话"
    )
    pending_facts: list[str] = Field(
        default_factory=list, description="不确定的信息，自动标注“待确认”"
    )
    task_state: TaskState = Field(default_factory=TaskState, description="当前任务状态")


class MemoryItem(BaseModel):
    """一条待写入长期记忆的条目。"""

    kind: MemoryKind = Field(description="记忆类别")
    content: str = Field(description="一句话记忆内容，不包含寒暄")
    city: str = Field(default="", description="关联城市；跨城市偏好留空")
    importance: int = Field(default=2, ge=1, le=5, description="重要度 1-5")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="置信度 0-1")


class MemoryExtraction(BaseModel):
    """长期记忆抽取结果。"""

    items: list[MemoryItem] = Field(default_factory=list, description="可长期保存的记忆")


class MemoryContext(BaseModel):
    """一次记忆加载的完整结果。"""

    summary: str = ""
    facts: dict = Field(default_factory=dict)
    task_state: dict = Field(default_factory=dict)
    context: str = ""
    turn_count: int = 0
