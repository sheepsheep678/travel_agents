"""可观测性：Prometheus 指标 + 进程内指标快照。

设计约定
--------
- ``prometheus_client`` 是可选依赖：未安装时所有打点自动降级为空操作，
  不影响主流程；``/metrics`` 返回 503 并提示安装。
- 同时维护一份进程内聚合（``snapshot()``），管理端看板无需部署
  Prometheus 也能看到 LLM 延迟、token、缓存命中率、熔断与节点耗时。
- 指标名统一 ``lvji_`` 前缀，避免与同实例其他服务冲突。
"""

from __future__ import annotations

import math
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Iterable, Optional

from langchain_core.callbacks import BaseCallbackHandler

from backend.app.core.config import settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - 依赖缺失时走降级分支
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter as _PromCounter,
        Gauge as _PromGauge,
        Histogram as _PromHistogram,
        generate_latest,
    )

    PROMETHEUS_AVAILABLE = True
except Exception:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    PROMETHEUS_AVAILABLE = False
    _PromCounter = None
    _PromGauge = None
    _PromHistogram = None
    generate_latest = None


class _NoopMetric:
    """prometheus_client 缺失时的空操作替身。"""

    def labels(self, *_: Any, **__: Any) -> "_NoopMetric":
        return self

    def inc(self, *_: Any, **__: Any) -> None:
        return None

    def observe(self, *_: Any, **__: Any) -> None:
        return None

    def set(self, *_: Any, **__: Any) -> None:
        return None


def _gauge(name: str, help_text: str, labels: Iterable[str] = ()) -> Any:
    if not PROMETHEUS_AVAILABLE:
        return _NoopMetric()
    try:
        return _PromGauge(name, help_text, list(labels))
    except ValueError:
        from prometheus_client import REGISTRY

        return REGISTRY._names_to_collectors.get(name) or _NoopMetric()


def _counter(name: str, help_text: str, labels: Iterable[str] = ()) -> Any:
    if not PROMETHEUS_AVAILABLE:
        return _NoopMetric()
    try:
        return _PromCounter(name, help_text, list(labels))
    except ValueError:
        # 模块被重复导入时复用已注册的指标
        from prometheus_client import REGISTRY

        return REGISTRY._names_to_collectors.get(name) or _NoopMetric()


def _histogram(
    name: str, help_text: str, labels: Iterable[str] = (), buckets: Iterable[float] = ()
) -> Any:
    if not PROMETHEUS_AVAILABLE:
        return _NoopMetric()
    try:
        return _PromHistogram(name, help_text, list(labels), buckets=list(buckets))
    except ValueError:
        from prometheus_client import REGISTRY

        return REGISTRY._names_to_collectors.get(name) or _NoopMetric()


_LLM_BUCKETS = (0.2, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300)
_NODE_BUCKETS = (0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 180)
_HTTP_BUCKETS = (0.005, 0.01, 0.05, 0.1, 0.5, 1, 5, 10, 60)

_LLM_REQUESTS = _counter(
    "lvji_llm_requests_total", "LLM 请求次数", ("model", "profile", "status")
)
_LLM_DURATION = _histogram(
    "lvji_llm_request_duration_seconds",
    "LLM 请求耗时（秒）",
    ("model", "profile"),
    _LLM_BUCKETS,
)
_LLM_TOKENS = _counter(
    "lvji_llm_tokens_total",
    "LLM token 用量",
    ("model", "profile", "kind", "source"),
)
_CACHE_REQUESTS = _counter(
    "lvji_cache_requests_total", "缓存读取结果", ("namespace", "result")
)
_CACHE_HIT_RATE = _gauge("lvji_cache_hit_rate", "缓存命中率（hit / (hit + miss)）")
_RERANK_REQUESTS = _counter("lvji_rerank_total", "精排调用结果", ("result",))
_NODE_DURATION = _histogram(
    "lvji_node_duration_seconds",
    "图节点耗时（秒）",
    ("graph", "node", "status"),
    _NODE_BUCKETS,
)
_TOOL_DURATION = _histogram(
    "lvji_tool_duration_seconds",
    "工具调用耗时（秒）",
    ("tool", "status"),
    _NODE_BUCKETS,
)
_HTTP_REQUESTS = _counter(
    "lvji_http_requests_total", "HTTP 请求次数", ("method", "path", "status")
)
_HTTP_DURATION = _histogram(
    "lvji_http_request_duration_seconds",
    "HTTP 请求耗时（秒）",
    ("method", "path"),
    _HTTP_BUCKETS,
)

_LOCK = threading.Lock()


class _Stats:
    """进程内聚合快照，管理端看板直接读取。"""

    def __init__(self) -> None:
        self.llm_requests: Counter[tuple[str, str, str]] = Counter()
        self.llm_latency: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0])
        self.llm_tokens: Counter[tuple[str, str, str, str]] = Counter()
        self.cache: Counter[tuple[str, str]] = Counter()
        self.rerank: Counter[str] = Counter()
        self.nodes: dict[tuple[str, str, str], list[float]] = defaultdict(
            lambda: [0.0, 0]
        )
        self.tools: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0])
        self.http: dict[tuple[str, str, str], list[float]] = defaultdict(
            lambda: [0.0, 0]
        )


_stats = _Stats()


def observe_llm_request(
    model: str,
    profile: str,
    status: str,
    seconds: float,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    source: str = "api",
) -> None:
    """记录一次 LLM 请求（延迟 + token + 状态）。"""
    model = str(model or "unknown")
    profile = str(profile or "unknown")
    status = str(status or "ok")
    _LLM_REQUESTS.labels(model, profile, status).inc()
    _LLM_DURATION.labels(model, profile).observe(max(0.0, seconds))
    if input_tokens or output_tokens:
        _LLM_TOKENS.labels(model, profile, "input", source).inc(max(0, input_tokens))
        _LLM_TOKENS.labels(model, profile, "output", source).inc(max(0, output_tokens))
    with _LOCK:
        _stats.llm_requests[(model, profile, status)] += 1
        slot = _stats.llm_latency[(model, profile)]
        slot[0] += max(0.0, seconds)
        slot[1] += 1
        if input_tokens or output_tokens:
            _stats.llm_tokens[(model, profile, "input", source)] += max(0, input_tokens)
            _stats.llm_tokens[(model, profile, "output", source)] += max(0, output_tokens)


def observe_cache(namespace: str, result: str) -> None:
    """记录一次缓存读取结果：hit / miss / bypass / error。"""
    namespace = str(namespace or "other")
    result = str(result or "unknown")
    _CACHE_REQUESTS.labels(namespace, result).inc()
    with _LOCK:
        _stats.cache[(namespace, result)] += 1
        hits = sum(count for (_, state), count in _stats.cache.items() if state == "hit")
        misses = sum(
            count for (_, state), count in _stats.cache.items() if state == "miss"
        )
        _CACHE_HIT_RATE.set(hits / (hits + misses) if hits + misses else 0.0)


def observe_rerank(result: str) -> None:
    """记录精排结果：ok / disabled / circuit_open / circuit_breaker。"""
    result = str(result or "unknown")
    _RERANK_REQUESTS.labels(result).inc()
    with _LOCK:
        _stats.rerank[result] += 1


def observe_node(graph: str, node: str, seconds: float, status: str = "ok") -> None:
    """记录图节点耗时。"""
    graph = str(graph or "graph")
    node = str(node or "unknown")
    status = str(status or "ok")
    _NODE_DURATION.labels(graph, node, status).observe(max(0.0, seconds))
    with _LOCK:
        slot = _stats.nodes[(graph, node, status)]
        slot[0] += max(0.0, seconds)
        slot[1] += 1


def observe_tool(tool: str, status: str, seconds: float) -> None:
    """记录工具调用耗时。"""
    tool = str(tool or "unknown")
    status = str(status or "ok")
    _TOOL_DURATION.labels(tool, status).observe(max(0.0, seconds))
    with _LOCK:
        slot = _stats.tools[(tool, status)]
        slot[0] += max(0.0, seconds)
        slot[1] += 1


def observe_http(method: str, path: str, status: int, seconds: float) -> None:
    """记录 HTTP 请求耗时。"""
    method = str(method or "GET")
    path = str(path or "unmatched")
    status_text = str(status)
    _HTTP_REQUESTS.labels(method, path, status_text).inc()
    _HTTP_DURATION.labels(method, path).observe(max(0.0, seconds))
    with _LOCK:
        slot = _stats.http[(method, path, status_text)]
        slot[0] += max(0.0, seconds)
        slot[1] += 1


def estimate_tokens(text: str) -> int:
    """粗略估算 token：CJK 按字计，其余按 4 字符一个 token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    return max(1, cjk + math.ceil((len(text) - cjk) / 4))


def _messages_text(messages: Any) -> str:
    """拼接 on_chat_model_start 收到的消息文本，用于缺省 token 估算。"""
    parts: list[str] = []
    for batch in messages or []:
        for message in batch or []:
            content = getattr(message, "content", "")
            if isinstance(content, str):
                parts.append(content)
    return "\n".join(parts)


def _response_text(response: Any) -> str:
    parts: list[str] = []
    for generation_list in getattr(response, "generations", []) or []:
        for generation in generation_list or []:
            message = getattr(generation, "message", None)
            content = getattr(message, "content", "") if message is not None else ""
            if isinstance(content, str):
                parts.append(content)
    return "\n".join(parts)


def _extract_usage(response: Any) -> tuple[int, int]:
    """从 LLMResult 中提取输入/输出 token，兼容 DashScope 兼容端点。"""
    llm_output = getattr(response, "llm_output", None) or {}
    usage = (
        llm_output.get("token_usage")
        or llm_output.get("usage")
        or llm_output.get("usage_metadata")
        or {}
    )
    input_tokens = int(
        usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    )
    output_tokens = int(
        usage.get("completion_tokens") or usage.get("output_tokens") or 0
    )
    if input_tokens or output_tokens:
        return input_tokens, output_tokens

    for generation_list in getattr(response, "generations", []) or []:
        for generation in generation_list or []:
            message = getattr(generation, "message", None)
            meta = getattr(message, "usage_metadata", None) or {}
            input_tokens += int(meta.get("input_tokens") or 0)
            output_tokens += int(meta.get("output_tokens") or 0)
    return input_tokens, output_tokens


class LLMMetricsCallback(BaseCallbackHandler):
    """挂到 ChatModel 上的回调：统计请求耗时与 token 用量。"""

    def __init__(self, model: str, profile: str) -> None:
        self.model = model
        self.profile = profile
        self._starts: dict[Any, tuple[float, str, int]] = {}

    def _start(self, run_id: Any, messages: Any = None) -> None:
        text = _messages_text(messages) if messages else ""
        self._starts.setdefault(
            run_id, (time.perf_counter(), text, estimate_tokens(text))
        )

    def on_chat_model_start(
        self, serialized: Any, messages: Any, *, run_id: Any, **_: Any
    ) -> None:
        self._start(run_id, messages)

    def on_llm_start(
        self, serialized: Any, prompts: Any, *, run_id: Any, **_: Any
    ) -> None:
        self._start(run_id)

    def on_llm_end(self, response: Any, *, run_id: Any, **_: Any) -> None:
        started, prompt_text, estimated_input = self._starts.pop(
            run_id, (time.perf_counter(), "", 0)
        )
        seconds = time.perf_counter() - started
        input_tokens, output_tokens = _extract_usage(response)
        source = "api"
        if not input_tokens and not output_tokens:
            source = "estimate"
            input_tokens = estimated_input
            output_tokens = estimate_tokens(_response_text(response))
        observe_llm_request(
            self.model,
            self.profile,
            "ok",
            seconds,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            source=source,
        )

    def on_llm_error(self, error: BaseException, *, run_id: Any, **_: Any) -> None:
        started, _, _ = self._starts.pop(run_id, (time.perf_counter(), "", 0))
        observe_llm_request(
            self.model, self.profile, "error", time.perf_counter() - started
        )
        logger.debug("LLM 调用失败", model=self.model, error=str(error))


class NodeMetricsCallback(BaseCallbackHandler):
    """LangGraph 节点耗时回调：只认带 ``langgraph_node`` 元数据的链事件。"""

    def __init__(self, graph: str) -> None:
        self.graph = graph
        self._starts: dict[Any, tuple[str, float]] = {}

    def on_chain_start(
        self, serialized: Any, inputs: Any, *, run_id: Any, metadata: Any = None, **_: Any
    ) -> None:
        node = (metadata or {}).get("langgraph_node")
        if node:
            self._starts[run_id] = (str(node), time.perf_counter())

    def on_chain_end(self, outputs: Any, *, run_id: Any, **_: Any) -> None:
        node, started = self._starts.pop(run_id, ("", 0.0))
        if node:
            observe_node(self.graph, node, time.perf_counter() - started)

    def on_chain_error(self, error: BaseException, *, run_id: Any, **_: Any) -> None:
        node, started = self._starts.pop(run_id, ("", 0.0))
        if node:
            observe_node(
                self.graph, node, time.perf_counter() - started, status="error"
            )


def _series(rows: dict) -> list[dict]:
    result = []
    for key, value in rows.items():
        labels = list(key if isinstance(key, tuple) else (key,))
        total, count = value
        result.append(
            {
                "labels": labels,
                "name": " · ".join(labels),
                "count": count,
                "total_ms": round(total * 1000, 2),
                "avg_ms": round(total * 1000 / max(count, 1), 2),
            }
        )
    return sorted(result, key=lambda item: item["count"], reverse=True)


def snapshot() -> dict[str, Any]:
    """返回进程内指标快照，供管理端看板使用（与 Prometheus 同源）。"""
    with _LOCK:
        llm_requests = [
            {"model": m, "profile": p, "status": s, "count": count}
            for (m, p, s), count in _stats.llm_requests.items()
        ]
        llm_latency = [
            {
                "model": m,
                "profile": p,
                "count": count,
                "avg_ms": round(total * 1000 / max(count, 1), 2),
            }
            for (m, p), (total, count) in _stats.llm_latency.items()
        ]
        llm_tokens = [
            {"model": m, "profile": p, "kind": kind, "source": src, "tokens": count}
            for (m, p, kind, src), count in _stats.llm_tokens.items()
        ]
        cache = [
            {"namespace": ns, "result": result, "count": count}
            for (ns, result), count in _stats.cache.items()
        ]
        rerank = dict(_stats.rerank)
        nodes = _series(_stats.nodes)
        tools = _series(_stats.tools)
        http = _series(_stats.http)

    hits = sum(row["count"] for row in cache if row["result"] == "hit")
    misses = sum(row["count"] for row in cache if row["result"] == "miss")
    total_reads = hits + misses
    cache_hit_rate = round(hits / total_reads, 4) if total_reads else 0.0

    return {
        "enabled": bool(settings.metrics.enabled),
        "prometheus_available": PROMETHEUS_AVAILABLE,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "llm": {
            "requests": sorted(llm_requests, key=lambda r: r["count"], reverse=True),
            "latency": sorted(llm_latency, key=lambda r: r["count"], reverse=True),
            "tokens": sorted(llm_tokens, key=lambda r: r["tokens"], reverse=True),
            "total_requests": sum(row["count"] for row in llm_requests),
            "total_tokens": sum(row["tokens"] for row in llm_tokens),
        },
        "cache": {
            "hits": hits,
            "misses": misses,
            "hit_rate": cache_hit_rate,
            "by_namespace": cache,
        },
        "rerank": {
            "ok": rerank.get("ok", 0),
            "disabled": rerank.get("disabled", 0),
            "circuit_open": rerank.get("circuit_open", 0),
            "circuit_breaker": rerank.get("circuit_breaker", 0),
            "total": sum(rerank.values()),
        },
        "nodes": nodes,
        "tools": tools,
        "http": http,
    }


def prometheus_payload() -> Optional[tuple[bytes, str]]:
    """生成 Prometheus 文本格式；未启用或依赖缺失时返回 None。"""
    if not settings.metrics.enabled or not PROMETHEUS_AVAILABLE or generate_latest is None:
        return None
    return generate_latest(), CONTENT_TYPE_LATEST


def instrument_app(app: Any) -> None:
    """给 FastAPI 挂上 HTTP 计数/延迟中间件（排除 /metrics 自身）。"""
    if not settings.metrics.enabled or not PROMETHEUS_AVAILABLE:
        if settings.metrics.enabled:
            logger.warning(
                "prometheus_client 未安装，/metrics 不可用；"
                "请执行 pip install prometheus_client"
            )
        return

    metrics_path = settings.metrics.path or "/metrics"

    @app.middleware("http")
    async def _metrics_middleware(request: Any, call_next: Any):
        if request.url.path == metrics_path:
            return await call_next(request)
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", None) or "unmatched"
        observe_http(request.method, path, response.status_code, time.perf_counter() - started)
        return response

    logger.info("HTTP 指标中间件已启用", path=metrics_path)
