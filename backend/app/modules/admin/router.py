"""管理端路由：评测入口、报告历史与指标快照。

所有接口都需要请求头 ``X-Admin-Token``，与知识库管理端上传共用
``KNOWLEDGE_ADMIN_TOKEN``；未配置时管理端整体禁用。
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header

from backend.app.core.config import settings
from backend.app.core.exceptions import PermissionDeniedError
from backend.app.modules.admin import service
from backend.app.modules.admin.schemas import (
    AdminDatasetResponse,
    AdminMetricsResponse,
    AdminReportDetailResponse,
    AdminReportListResponse,
    EvalRunDetailResponse,
    EvalRunListResponse,
    EvalRunStartRequest,
    EvalRunStartResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(
    x_admin_token: str = Header("", alias="X-Admin-Token"),
) -> None:
    """校验管理端令牌；未配置时拒绝所有管理端请求。"""
    expected = settings.knowledge.admin_token.strip()
    if not expected:
        raise PermissionDeniedError("管理端未启用：请配置 KNOWLEDGE_ADMIN_TOKEN")
    if not secrets.compare_digest(x_admin_token, expected):
        raise PermissionDeniedError("管理端令牌无效")


@router.get(
    "/datasets",
    response_model=AdminDatasetResponse,
    summary="评测数据集概览",
    dependencies=[Depends(require_admin)],
)
async def admin_datasets() -> AdminDatasetResponse:
    """返回 base / hard / all 与对话评测集的条数、类型分布和样例。"""
    return AdminDatasetResponse(**service.list_datasets())


@router.get(
    "/metrics",
    response_model=AdminMetricsResponse,
    summary="管理端指标快照",
    dependencies=[Depends(require_admin)],
)
async def admin_metrics() -> AdminMetricsResponse:
    """进程内指标：LLM 延迟/token、缓存命中率、精排熔断、节点耗时。"""
    return AdminMetricsResponse(**service.metrics_summary())


@router.get(
    "/eval/runs",
    response_model=EvalRunListResponse,
    summary="评测任务列表",
    dependencies=[Depends(require_admin)],
)
async def admin_eval_runs() -> EvalRunListResponse:
    """列出当前进程内的评测任务（含已完成任务与日志尾部）。"""
    return EvalRunListResponse(**service.list_runs())


@router.post(
    "/eval/runs",
    response_model=EvalRunStartResponse,
    summary="启动评测任务",
    dependencies=[Depends(require_admin)],
)
async def admin_start_eval(request: EvalRunStartRequest) -> EvalRunStartResponse:
    """启动检索或对话评测；子进程执行，接口立即返回 run_id。"""
    return EvalRunStartResponse(success=True, run=await service.start_run(request))


@router.get(
    "/eval/runs/{run_id}",
    response_model=EvalRunDetailResponse,
    summary="评测任务状态",
    dependencies=[Depends(require_admin)],
)
async def admin_eval_run(run_id: str) -> EvalRunDetailResponse:
    """轮询任务状态；完成后返回 report_summary 与 report_name。"""
    data = service.get_run(run_id)
    return EvalRunDetailResponse(**data)


@router.post(
    "/eval/runs/{run_id}/cancel",
    response_model=EvalRunStartResponse,
    summary="取消评测任务",
    dependencies=[Depends(require_admin)],
)
async def admin_cancel_eval(run_id: str) -> EvalRunStartResponse:
    """终止评测子进程并标记为 cancelled。"""
    return EvalRunStartResponse(success=True, run=service.cancel_run(run_id))


@router.get(
    "/eval/reports",
    response_model=AdminReportListResponse,
    summary="历史评测报告",
    dependencies=[Depends(require_admin)],
)
async def admin_reports() -> AdminReportListResponse:
    """列出 results 目录下的历史报告与头部指标。"""
    return AdminReportListResponse(**service.list_reports())


@router.get(
    "/eval/reports/{name}",
    response_model=AdminReportDetailResponse,
    summary="读取完整评测报告",
    dependencies=[Depends(require_admin)],
)
async def admin_report(name: str) -> AdminReportDetailResponse:
    """按文件名读取完整 JSON 报告。"""
    return AdminReportDetailResponse(**service.get_report(name))
