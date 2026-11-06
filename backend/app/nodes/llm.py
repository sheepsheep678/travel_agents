import json
import logging

from langchain.chat_models import init_chat_model
from langchain_community.embeddings import DashScopeEmbeddings

from backend.app.services.config import settings

logger = logging.getLogger(__name__)

_llm = None
_fast_llm = None
_embedding_model = None


def _parse_extra_body(raw: str):
    """解析 OPENAI_FAST_EXTRA_BODY 等原始 JSON 配置，非法时忽略"""
    if not raw or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("[LLM] extra_body 不是合法 JSON，已忽略: %s", raw)
        return None
    return value if isinstance(value, dict) else None


def _thinking_extra_body(profile: str):
    """按 profile 生成关闭 thinking 的额外请求体（当前 DashScope 兼容端点）。

    若端点不支持该参数而报 400，把 OPENAI_DISABLE_THINKING /
    OPENAI_PLAN_DISABLE_THINKING 设为 false 即可回退；其他 provider 可用
    OPENAI_FAST_EXTRA_BODY / OPENAI_PLAN_EXTRA_BODY 直接覆盖。
    """
    is_fast = profile == "fast"
    parsed = _parse_extra_body(
        settings.openai_fast_extra_body if is_fast else settings.openai_plan_extra_body
    )
    if parsed:
        return parsed
    disable = (settings.openai_disable_thinking if is_fast
               else settings.openai_plan_disable_thinking)
    if disable:
        return {"enable_thinking": False}
    return None


def _build_model(profile: str):
    is_fast = profile == "fast"
    kwargs = {
        "model": settings.openai_fast_model_id if is_fast else settings.openai_model_id,
        "model_provider": "openai",
        "base_url": settings.openai_base_url,
        "api_key": settings.openai_api_key,
        "temperature": settings.openai_fast_temperature if is_fast else 0.4,
        "timeout": settings.openai_timeout if is_fast else settings.openai_plan_timeout,
        "max_retries": settings.openai_max_retries,
    }
    max_tokens = settings.openai_fast_max_tokens if is_fast else settings.openai_max_tokens
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    extra_body = _thinking_extra_body(profile)
    if extra_body:
        kwargs["extra_body"] = extra_body

    logger.info("[LLM] profile=%s model=%s timeout=%ss max_tokens=%s extra_body=%s",
                profile, kwargs["model"], kwargs["timeout"],
                kwargs.get("max_tokens"), extra_body)
    return init_chat_model(**kwargs)


def get_llm():
    global _llm
    if _llm is None:
        _llm = _build_model("main")
    return _llm


def get_fast_llm():
    """快模型用于 RAG / 评估 / 景点描述等轻量任务；未配置时回退主模型同一实例"""
    global _fast_llm
    if not settings.openai_fast_model_id.strip():
        return get_llm()
    if _fast_llm is None:
        _fast_llm = _build_model("fast")
    return _fast_llm


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = DashScopeEmbeddings(model=settings.embedding_model_name)
    return _embedding_model


if __name__ == "__main__":
    get_llm()
    get_fast_llm()
    get_embedding_model()
