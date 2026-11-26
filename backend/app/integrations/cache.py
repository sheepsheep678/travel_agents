"""Redis 缓存：工具结果、会话历史、向量检索结果（默认 TTL 60 秒）。

设计约定：
- Redis 不可用时所有读写静默降级为直通，绝不阻断业务流程；
- 所有 key 带 ``REDIS_KEY_PREFIX`` 前缀，避免与同实例其他数据冲突；
- 工具统一通过 ``wrap_tool`` 包装，调用方不需要关心缓存细节。
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from langchain_core.tools import BaseTool, StructuredTool
from redis.asyncio import Redis

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.core.metrics import observe_cache, observe_tool

logger = get_logger(__name__)

_client: Optional[Redis] = None


def _ttl_seconds() -> int:
    """读取缓存 TTL，非法值回退 60 秒。"""
    try:
        return max(1, int(settings.redis.ttl))
    except (TypeError, ValueError):
        return 60


def _safe_url(url: str) -> str:
    """隐藏连接串里的密码，避免日志泄露。"""
    try:
        parts = urlsplit(url)
        if not parts.password:
            return url
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        netloc = f"{parts.username or ''}:***@{host}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except ValueError:
        return "redis://***"


async def init_cache() -> None:
    """连接 Redis；失败时缓存降级为直通，不阻断启动。"""
    global _client
    if not settings.redis.enabled:
        logger.info("Redis 缓存已关闭")
        return
    try:
        client = Redis.from_url(
            settings.redis.url,
            decode_responses=True,
            socket_connect_timeout=settings.redis.timeout,
            socket_timeout=settings.redis.timeout,
        )
        await client.ping()
    except Exception as exc:
        logger.warning(
            "Redis 不可用，缓存降级为直通",
            url=_safe_url(settings.redis.url),
            error=str(exc),
        )
        return
    _client = client
    logger.info("Redis 缓存已就绪", url=_safe_url(settings.redis.url), ttl=_ttl_seconds())


async def close_cache() -> None:
    """关闭 Redis 连接。"""
    global _client
    client, _client = _client, None
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            logger.warning("关闭 Redis 连接失败", exc_info=True)
    logger.info("Redis 缓存已关闭")


def cache_enabled() -> bool:
    """缓存是否可用。"""
    return _client is not None


async def check_cache() -> bool:
    """健康检查：PING。"""
    if _client is None:
        return False
    try:
        await _client.ping()
        return True
    except Exception as exc:
        logger.warning("Redis 健康检查失败", error=str(exc))
        return False


def make_key(namespace: str, *parts: Any) -> str:
    """生成缓存键：前缀 + 命名空间 + 参数摘要。"""
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"{settings.redis.key_prefix}:{namespace}:{digest}"


def _namespace_of(key: str) -> str:
    """从缓存键里取命名空间；格式不符时归入 other。"""
    parts = key.split(":", 2)
    return parts[1] if len(parts) >= 3 else "other"


async def cache_get_json(key: str) -> Any:
    """读取 JSON 缓存；未命中或出错返回 None。"""
    namespace = _namespace_of(key)
    if _client is None:
        observe_cache(namespace, "bypass")
        return None
    try:
        raw = await _client.get(key)
    except Exception as exc:
        observe_cache(namespace, "error")
        logger.debug("读取缓存失败", key=key, error=str(exc))
        return None
    if raw is None:
        observe_cache(namespace, "miss")
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        observe_cache(namespace, "error")
        return None
    observe_cache(namespace, "hit")
    return value


async def cache_set_json(key: str, value: Any, ttl: Optional[int] = None) -> None:
    """写入 JSON 缓存；序列化失败或 Redis 出错时静默跳过。"""
    if _client is None:
        return
    try:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        await _client.set(key, payload, ex=ttl or _ttl_seconds())
    except Exception as exc:
        logger.debug("写入缓存失败", key=key, error=str(exc))


async def cache_delete(key: str) -> None:
    """删除单个缓存键；Redis 出错时静默跳过。"""
    if _client is None:
        return
    try:
        await _client.delete(key)
    except Exception as exc:
        logger.debug("删除缓存失败", key=key, error=str(exc))


def _cacheable(value: Any) -> Any:
    """把工具返回值转成可 JSON 序列化的结构；失败返回 None。"""
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return None


def wrap_tool(tool: BaseTool, *, scope: str = "") -> BaseTool:
    """给工具套一层结果缓存：按工具名 + 参数 + 作用域命中。"""

    async def _cached(**kwargs: Any) -> Any:
        """先查缓存，未命中再调用原工具并回写。"""
        key = make_key("tool", tool.name, scope, kwargs)
        cached = await cache_get_json(key)
        if cached is not None:
            logger.debug("工具命中缓存", tool=tool.name)
            return cached
        started = time.perf_counter()
        try:
            result = await tool.ainvoke(kwargs)
        except Exception:
            observe_tool(tool.name, "error", time.perf_counter() - started)
            raise
        observe_tool(tool.name, "ok", time.perf_counter() - started)
        payload = _cacheable(result)
        if payload is not None:
            await cache_set_json(key, payload)
        return result

    return StructuredTool.from_function(
        coroutine=_cached,
        name=tool.name,
        description=tool.description or "",
        args_schema=tool.args_schema,
        metadata=getattr(tool, "metadata", None),
    )
