"""LLM / Embedding 客户端工厂（进程级单例）。"""

from __future__ import annotations

import json
from typing import Any, Optional

from langchain.chat_models import init_chat_model
from langchain_community.embeddings import DashScopeEmbeddings

from backend.app.core.config import settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

_llm: Any = None
_fast_llm: Any = None
_embedding_model: Any = None


def _parse_extra_body(raw: str) -> Optional[dict]:
    """解析 EXTRA_BODY 原始 JSON 配置，非法时忽略。"""
    if not raw or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("extra_body 不是合法 JSON，已忽略", raw=raw)
        return None
    return value if isinstance(value, dict) else None


def _thinking_extra_body(profile: str) -> Optional[dict]:
    """按 profile 生成关闭 thinking 的额外请求体（当前 DashScope 兼容端点）。

    若端点不支持该参数而报 400，把 OPENAI_DISABLE_THINKING /
    OPENAI_PLAN_DISABLE_THINKING 设为 false 即可回退；其他 provider 可用
    OPENAI_FAST_EXTRA_BODY / OPENAI_PLAN_EXTRA_BODY 直接覆盖。
    """
    is_fast = profile == "fast"
    llm_cfg = settings.llm
    parsed = _parse_extra_body(
        llm_cfg.fast_extra_body if is_fast else llm_cfg.plan_extra_body
    )
    if parsed:
        return parsed
    disable = (
        llm_cfg.disable_thinking if is_fast else llm_cfg.plan_disable_thinking
    )
    return {"enable_thinking": False} if disable else None


def _build_model(profile: str):
    is_fast = profile == "fast"
    llm_cfg = settings.llm
    kwargs: dict[str, Any] = {
        "model": llm_cfg.fast_model_id if is_fast else llm_cfg.model_id,
        "model_provider": "openai",
        "base_url": llm_cfg.base_url,
        "api_key": llm_cfg.api_key,
        "temperature": llm_cfg.fast_temperature if is_fast else 0.4,
        "timeout": llm_cfg.timeout if is_fast else llm_cfg.plan_timeout,
        "max_retries": llm_cfg.max_retries,
    }
    max_tokens = llm_cfg.fast_max_tokens if is_fast else llm_cfg.max_tokens
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    extra_body = _thinking_extra_body(profile)
    if extra_body:
        kwargs["extra_body"] = extra_body

    logger.info(
        "LLM 初始化",
        profile=profile,
        model=kwargs["model"],
        timeout=kwargs["timeout"],
        max_tokens=kwargs.get("max_tokens"),
        extra_body=extra_body,
    )
    return init_chat_model(**kwargs)


def get_llm():
    """主模型：行程规划 / 复杂推理。"""
    global _llm
    if _llm is None:
        _llm = _build_model("main")
    return _llm


def get_fast_llm():
    """快模型：RAG / 评估 / 景点描述；未配置时回退主模型。"""
    global _fast_llm
    if not settings.llm.fast_model_id.strip():
        return get_llm()
    if _fast_llm is None:
        _fast_llm = _build_model("fast")
    return _fast_llm


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = DashScopeEmbeddings(
            model=settings.llm.embedding_model_name,
            dashscope_api_key=settings.llm.api_key,
        )
    return _embedding_model


if __name__ == "__main__":
    get_llm()
    get_fast_llm()
    get_embedding_model()
