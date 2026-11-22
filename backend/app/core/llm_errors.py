"""把大模型上游错误转换成用户可读的提示。

DashScope/OpenAI 兼容接口在欠费、未开通模型、Key 无效等情况下会返回很长的
JSON（例如 ``Arrearage`` / ``AccessDenied.Unpurchased``）。直接拼进 SSE 会让
前端显示一大段原始报错，这里统一收敛成中文提示，并保留 request_id 便于排查。
"""

from __future__ import annotations

import re
from typing import Optional

_REQUEST_ID_RE = re.compile(r"request_id['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_-]+)")


def _request_id(text: str) -> str:
    match = _REQUEST_ID_RE.search(text or "")
    return match.group(1) if match else ""


def llm_error_kind(exc: BaseException) -> Optional[str]:
    """返回错误类型：billing / permission / auth / rate_limit / timeout / None。"""
    text = str(exc).lower()
    if "arrearage" in text or "overdue" in text or "good standing" in text:
        return "billing"
    if "accessdenied" in text or "unpurchased" in text or "access denied" in text:
        return "permission"
    if "invalid api key" in text or "incorrect api key" in text or "unauthorized" in text:
        return "auth"
    if "rate limit" in text or "too many requests" in text or " 429" in text:
        return "rate_limit"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    return None


def format_llm_error(exc: BaseException) -> str:
    """把异常转成简短中文提示；未知错误保留前 300 字符。"""
    kind = llm_error_kind(exc)
    if kind == "billing":
        message = "大模型账户欠费或权限已过期，请到阿里云百炼控制台充值并恢复模型权限后重试"
    elif kind == "permission":
        message = "当前大模型账户没有该模型权限，请检查 OPENAI_MODEL_ID / OPENAI_FAST_MODEL_ID 是否已开通"
    elif kind == "auth":
        message = "大模型 API Key 无效或未授权，请检查 OPENAI_API_KEY"
    elif kind == "rate_limit":
        message = "大模型请求频率超限，请稍后重试"
    elif kind == "timeout":
        message = "大模型请求超时，请稍后重试"
    else:
        message = f"大模型调用失败：{str(exc)[:300]}"

    request_id = _request_id(str(exc))
    if request_id:
        message += f"（request_id: {request_id}）"
    return message
