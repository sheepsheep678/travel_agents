"""管理端业务：评测子进程调度、报告历史、数据集概览与指标快照。

评测入口复用现有 CLI（``retrieval_eval`` / ``chat_eval``），通过独立
Python 子进程执行，避免在 API 进程内改动 Milvus 全局配置或阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from backend.app.core.config import settings
from backend.app.core.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
)
from backend.app.core.logging import get_logger
from backend.app.modules.admin.schemas import EvalRunStartRequest

logger = get_logger(__name__)

# backend/app/modules/admin/service.py -> backend/app -> backend -> repo root
_APP_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[4]
_RESULTS_DIR = _APP_DIR / "evaluation" / "results"
_DATASETS_DIR = _APP_DIR / "evaluation" / "datasets"
_RETRIEVAL_DATASETS = {
    "base": _DATASETS_DIR / "retrieval_eval.jsonl",
    "hard": _DATASETS_DIR / "retrieval_eval_hard.jsonl",
}
_CHAT_DATASET = _DATASETS_DIR / "chat_eval.jsonl"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_LOCK = asyncio.Lock()
_RUNS: dict[str, "EvalRun"] = {}
_ACTIVE: dict[str, str] = {}


@dataclass
class EvalRun:
    """一次评测子进程的运行状态。"""

    id: str
    kind: str
    status: str
    options: dict[str, Any]
    started_at: str
    log: deque[str] = field(default_factory=deque)
    finished_at: Optional[str] = None
    report_name: Optional[str] = None
    error: Optional[str] = None
    returncode: Optional[int] = None
    output_path: Optional[Path] = None
    process: Any = None
    task: Any = None

    def info(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "options": self.options,
            "log": list(self.log),
            "report_name": self.report_name,
            "error": self.error,
            "returncode": self.returncode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ---------------------------------------------------------------------------
# 数据集与报告
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL；文件缺失时返回空列表。"""
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _safe_report_name(name: str) -> str:
    """只允许 results 目录下的普通 .json 文件名。"""
    if not name or Path(name).name != name or not name.endswith(".json"):
        raise BadRequestError("报告文件名不合法")
    return name


def _report_kind(name: str, data: dict[str, Any]) -> str:
    """根据文件名与内容判断报告类型。"""
    if "ablation" in data or "results" in data:
        return "retrieval"
    if "summary" in data:
        return "chat"
    return "other"


def _metric(metrics: dict[str, Any], prefix: str) -> Any:
    """取 mrr@10 / ndcg@10 这类带 top_k 后缀的指标。"""
    for key, value in metrics.items():
        if key.startswith(prefix):
            return value
    return None


def _report_summary(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """提取报告头部信息，列表页无需加载完整明细。"""
    if kind == "retrieval":
        results = data.get("results") or {}
        primary = results.get("hybrid") or next(iter(results.values()), {})
        metrics = primary.get("metrics") or {}
        return {
            "dataset": data.get("dataset"),
            "queries": data.get("queries"),
            "top_k": data.get("top_k"),
            "rerank": data.get("rerank"),
            "hyde_mode": data.get("hyde_mode"),
            "headline": {
                "recall@1": metrics.get("recall@1"),
                "recall@5": metrics.get("recall@5"),
                "mrr": _metric(metrics, "mrr@"),
                "ndcg": _metric(metrics, "ndcg@"),
                "latency": metrics.get("latency_ms"),
            },
            "usage": data.get("usage"),
        }
    overall = (data.get("summary") or {}).get("overall") or {}
    return {
        "headline": overall,
        "by_category": (data.get("summary") or {}).get("by_category") or {},
        "duration_seconds": data.get("duration_seconds"),
    }


def _retrieval_sha(paths: list[Path]) -> str:
    """与 retrieval_eval.dataset_sha256 保持一致：文件名 + 内容。"""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _sample(row: dict[str, Any]) -> dict[str, Any]:
    """数据集预览：只截取前 160 字，避免响应过大。"""
    return {
        "id": row.get("id"),
        "type": row.get("type") or row.get("category") or "base",
        "city": row.get("city") or "",
        "title": row.get("title") or "",
        "query": row.get("query") or "",
        "text_preview": (row.get("text") or "")[:160],
        "filter": row.get("filter") or "",
    }


def list_datasets() -> dict[str, Any]:
    """返回 base / hard / all 与对话评测集的元数据和样例。"""
    retrieval: list[dict[str, Any]] = []
    base_rows = _read_jsonl(_RETRIEVAL_DATASETS["base"])
    hard_rows = _read_jsonl(_RETRIEVAL_DATASETS["hard"])
    for key, path, rows, sha_paths in (
        ("base", _RETRIEVAL_DATASETS["base"], base_rows, [_RETRIEVAL_DATASETS["base"]]),
        ("hard", _RETRIEVAL_DATASETS["hard"], hard_rows, [_RETRIEVAL_DATASETS["hard"]]),
        (
            "all",
            _RETRIEVAL_DATASETS["base"],
            base_rows + hard_rows,
            [_RETRIEVAL_DATASETS["base"], _RETRIEVAL_DATASETS["hard"]],
        ),
    ):
        retrieval.append(
            {
                "key": key,
                "file": path.name if key != "all" else "retrieval_eval.jsonl + retrieval_eval_hard.jsonl",
                "count": len(rows),
                "sha256": _retrieval_sha(sha_paths),
                "types": dict(Counter(row.get("type") or "base" for row in rows)),
                "samples": [_sample(row) for row in rows[:4]],
            }
        )

    chat_rows = _read_jsonl(_CHAT_DATASET)
    chat = {
        "file": _CHAT_DATASET.name,
        "count": len(chat_rows),
        "sha256": hashlib.sha256(_CHAT_DATASET.read_bytes()).hexdigest()
        if _CHAT_DATASET.exists()
        else "",
        "categories": dict(Counter(row.get("category") or "unknown" for row in chat_rows)),
        "samples": [_sample(row) for row in chat_rows[:6]],
    }
    return {"success": True, "retrieval": retrieval, "chat": chat}


def list_reports() -> dict[str, Any]:
    """列出 results 目录下的历史报告（按修改时间倒序）。"""
    if not _RESULTS_DIR.exists():
        return {"success": True, "items": []}
    items: list[dict[str, Any]] = []
    paths = sorted(
        _RESULTS_DIR.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in paths[:100]:
        if path.name.startswith("retrieval_eval_ingested"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        kind = _report_kind(path.name, data)
        if kind == "other":
            continue
        summary = _report_summary(kind, data)
        items.append(
            {
                "name": path.name,
                "kind": kind,
                "generated_at": data.get("generated_at") or "",
                "duration_seconds": data.get("duration_seconds"),
                "size_bytes": path.stat().st_size,
                **summary,
            }
        )
    return {"success": True, "items": items}


def get_report(name: str) -> dict[str, Any]:
    """读取一份完整报告。"""
    safe = _safe_report_name(name)
    path = _RESULTS_DIR / safe
    if not path.exists():
        raise NotFoundError("报告不存在")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BadRequestError(f"报告解析失败: {exc}") from exc
    return {
        "success": True,
        "name": safe,
        "kind": _report_kind(safe, data),
        "report": data,
    }


# ---------------------------------------------------------------------------
# 评测子进程
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _prune_runs() -> None:
    """清理超过 TTL 的已结束任务。"""
    ttl = timedelta(seconds=max(60, settings.evaluation.admin_run_ttl_seconds))
    now = datetime.now()
    for run_id, run in list(_RUNS.items()):
        if run.status == "running" or not run.finished_at:
            continue
        try:
            finished = datetime.fromisoformat(run.finished_at)
        except ValueError:
            continue
        if now - finished > ttl:
            _RUNS.pop(run_id, None)


def _append_log(run: EvalRun, line: str) -> None:
    """追加日志行并限制长度；去掉控制台颜色码。"""
    text = _ANSI_RE.sub("", line).rstrip()
    if text:
        run.log.append(text[:2000])


def _build_command(request: EvalRunStartRequest, output: Path) -> list[str]:
    """把请求转换成 CLI 参数。"""
    python = sys.executable or "python"
    if request.kind == "retrieval":
        cmd = [
            python,
            "-m",
            "backend.app.evaluation.retrieval_eval",
            "--dataset",
            request.dataset,
            "--top-k",
            str(request.top_k),
            "--hyde",
            request.hyde,
            "--hyde-concurrency",
            str(request.hyde_concurrency),
            "--output",
            str(output),
        ]
        if request.limit:
            cmd.extend(["--limit", str(request.limit)])
        if not request.rerank:
            cmd.append("--no-rerank")
        if request.rebuild:
            cmd.append("--rebuild")
        return cmd

    cmd = [
        python,
        "-m",
        "backend.app.evaluation.chat_eval",
        "--concurrency",
        str(request.concurrency),
        "--output",
        str(output),
    ]
    if request.limit:
        cmd.extend(["--limit", str(request.limit)])
    if request.category:
        cmd.extend(["--category", request.category])
    if not request.judge:
        cmd.append("--no-judge")
    return cmd


async def _run_process(run: EvalRun, cmd: list[str]) -> None:
    """执行子进程并持续把 stdout 写入任务日志。"""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    output = run.output_path
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(_REPO_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        run.process = proc
        _append_log(run, f"$ {' '.join(cmd)}")
        assert proc.stdout is not None
        async for raw in proc.stdout:
            for line in raw.decode("utf-8", errors="replace").splitlines():
                _append_log(run, line)
        run.returncode = await proc.wait()
        if run.status == "cancelled":
            pass
        elif run.returncode == 0 and output is not None and output.exists():
            run.status = "succeeded"
            run.report_name = output.name
        else:
            run.status = "failed"
            tail = [line for line in run.log if line.strip()][-6:]
            run.error = "；".join(tail) or f"评测进程退出码 {run.returncode}"
    except asyncio.CancelledError:
        run.status = "cancelled"
        if run.process is not None:
            try:
                run.process.terminate()
            except ProcessLookupError:
                pass
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)
        logger.exception("评测子进程失败", run_id=run.id)
    finally:
        run.finished_at = _now()
        run.process = None
        _ACTIVE.pop(run.kind, None)
        logger.info(
            "评测任务结束",
            run_id=run.id,
            kind=run.kind,
            status=run.status,
            returncode=run.returncode,
        )


async def start_run(request: EvalRunStartRequest) -> dict[str, Any]:
    """启动一次评测；同类型同时只允许一个任务，避免争抢模型与 Milvus。"""
    async with _LOCK:
        _prune_runs()
        active = _ACTIVE.get(request.kind)
        if active and _RUNS.get(active) and _RUNS[active].status == "running":
            raise ConflictError(
                f"{request.kind} 评测正在运行，请等待完成或先取消"
            )

        run_id = uuid.uuid4().hex[:12]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = "retrieval_eval" if request.kind == "retrieval" else "chat_eval"
        output = _RESULTS_DIR / f"{prefix}_admin_{timestamp}_{run_id[:6]}.json"
        output.parent.mkdir(parents=True, exist_ok=True)

        run = EvalRun(
            id=run_id,
            kind=request.kind,
            status="running",
            options=request.model_dump(),
            started_at=_now(),
            log=deque(maxlen=max(20, settings.evaluation.admin_log_lines)),
            output_path=output,
        )
        _RUNS[run_id] = run
        _ACTIVE[request.kind] = run_id
        run.task = asyncio.create_task(_run_process(run, _build_command(request, output)))
        logger.info("评测任务已启动", run_id=run_id, kind=request.kind)
        return run.info()


def list_runs() -> dict[str, Any]:
    """列出最近的任务（内存态，最多 50 条）。"""
    _prune_runs()
    runs = sorted(_RUNS.values(), key=lambda run: run.started_at, reverse=True)
    return {"success": True, "runs": [run.info() for run in runs[:50]]}


def get_run(run_id: str) -> dict[str, Any]:
    """读取任务状态，并在完成后附带报告摘要。"""
    run = _RUNS.get(run_id)
    if run is None:
        raise NotFoundError("评测任务不存在或已过期")
    summary = None
    if run.report_name:
        try:
            data = json.loads(
                (_RESULTS_DIR / run.report_name).read_text(encoding="utf-8")
            )
            summary = _report_summary(_report_kind(run.report_name, data), data)
        except Exception:
            summary = None
    return {"success": True, "run": run.info(), "report_summary": summary}


def cancel_run(run_id: str) -> dict[str, Any]:
    """终止正在运行的评测子进程。"""
    run = _RUNS.get(run_id)
    if run is None:
        raise NotFoundError("评测任务不存在或已过期")
    if run.status != "running":
        return run.info()
    run.status = "cancelled"
    if run.process is not None:
        try:
            run.process.terminate()
        except ProcessLookupError:
            pass
    if run.task is not None and not run.task.done():
        run.task.cancel()
    logger.info("评测任务已取消", run_id=run_id)
    return run.info()


def metrics_summary() -> dict[str, Any]:
    """进程内指标快照（与 /metrics 同源）。"""
    from backend.app.core.metrics import snapshot

    return {"success": True, "metrics": snapshot()}
