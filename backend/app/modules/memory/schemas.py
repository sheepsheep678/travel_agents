"""记忆管理接口的请求 / 响应模型。"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class MemoryOut(BaseModel):
    id: str
    kind: str
    content: str
    city: str = ""
    importance: int = 0
    confidence: float = 0.0
    status: str = "confirmed"
    source_session_id: str = ""
    created_at: int = 0
    last_used_at: int = 0

    @classmethod
    def from_row(cls, row: dict) -> "MemoryOut":
        """把 Milvus 查询行转成响应模型。"""
        return cls(
            id=str(row.get("id") or ""),
            kind=str(row.get("kind") or ""),
            content=str(row.get("content") or ""),
            city=str(row.get("city") or ""),
            importance=int(row.get("importance") or 0),
            confidence=float(row.get("confidence") or 0.0),
            status=str(row.get("status") or "confirmed"),
            source_session_id=str(row.get("source_session_id") or ""),
            created_at=int(row.get("created_at") or 0),
            last_used_at=int(row.get("last_used_at") or 0),
        )


class MemoryListResponse(BaseModel):
    success: bool = True
    memories: List[MemoryOut] = Field(default_factory=list)
    count: int = 0


class SessionMemoryOut(BaseModel):
    session_id: str
    summary: str = ""
    facts: Dict[str, Any] = Field(default_factory=dict)
    task_state: Dict[str, Any] = Field(default_factory=dict)
    turn_count: int = 0
    updated_at: str = ""


class SessionMemoryResponse(BaseModel):
    success: bool = True
    memory: SessionMemoryOut


class MemoryDeleteResponse(BaseModel):
    success: bool = True
    deleted: int = 0
    message: str = ""
