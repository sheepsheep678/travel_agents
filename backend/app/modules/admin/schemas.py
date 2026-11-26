"""管理端请求 / 响应模型。"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class EvalRunStartRequest(BaseModel):
    """启动一次离线评测；retrieval 与 chat 共用入口。"""

    kind: Literal["retrieval", "chat"] = Field(description="retrieval / chat")
    # 检索评测
    dataset: Literal["base", "hard", "all"] = "base"
    top_k: int = Field(default=10, ge=1, le=50)
    limit: int = Field(default=0, ge=0, le=1000)
    rerank: bool = True
    hyde: Literal["off", "on", "both"] = "off"
    rebuild: bool = False
    hyde_concurrency: int = Field(default=4, ge=1, le=16)
    # 对话评测
    category: Literal["", "precise", "fuzzy", "dangerous"] = ""
    concurrency: int = Field(default=3, ge=1, le=10)
    judge: bool = True


class EvalRunInfo(BaseModel):
    """评测任务状态（日志只保留尾部若干行）。"""

    id: str
    kind: str
    status: str
    options: dict[str, Any] = Field(default_factory=dict)
    log: list[str] = Field(default_factory=list)
    report_name: Optional[str] = None
    error: Optional[str] = None
    returncode: Optional[int] = None
    started_at: str
    finished_at: Optional[str] = None


class EvalRunStartResponse(BaseModel):
    success: bool = True
    run: EvalRunInfo


class EvalRunListResponse(BaseModel):
    success: bool = True
    runs: list[EvalRunInfo]


class EvalRunDetailResponse(BaseModel):
    success: bool = True
    run: EvalRunInfo
    report_summary: Optional[dict[str, Any]] = None


class AdminDatasetResponse(BaseModel):
    success: bool = True
    retrieval: list[dict[str, Any]]
    chat: dict[str, Any]


class AdminReportListResponse(BaseModel):
    success: bool = True
    items: list[dict[str, Any]]


class AdminReportDetailResponse(BaseModel):
    success: bool = True
    name: str
    kind: str
    report: dict[str, Any]


class AdminMetricsResponse(BaseModel):
    success: bool = True
    metrics: dict[str, Any]
