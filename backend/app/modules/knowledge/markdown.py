"""用快模型整理文档 Markdown（只排版，不改事实）。

MinerU / pypdf / Qwen-VL 抽取出来的文本常有页眉页脚、断裂表格、重复标题。
这里让 LLM 只做「结构整理」：统一标题层级、修复表格和列表、合并被硬换行
切断的句子；明确禁止增删或改写事实，失败时原样返回。
"""

from __future__ import annotations

import asyncio
import re

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.integrations.llm import get_fast_llm

logger = get_logger(__name__)

_SYSTEM_PROMPT = """你是文档排版助手。只整理 Markdown 格式，不得增删或改写事实。
规则：
1. 统一标题层级（# / ## / ###），保留原文标题文字。
2. 修复被硬换行拆断的句子；表格必须保留表头、分隔行和每一行数据。
3. 删除页眉、页脚、页码、重复水印等与正文无关的内容。
4. 不得新增景点、价格、时间、路线、数字或任何事实；不确定的内容原样保留。
5. 只输出整理后的 Markdown 正文，不要解释，不要加代码围栏。"""


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


async def optimize_markdown(text: str, source_type: str, title: str = "") -> str:
    """整理 Markdown；未启用、过短、超长或调用失败时返回原文。"""
    text = (text or "").strip()
    if not text or not settings.knowledge.markdown_normalize:
        return text
    if len(text) < 120:
        return text
    if len(text) > settings.knowledge.markdown_normalize_max_chars:
        logger.info(
            "文档超过 Markdown 整理上限，跳过 LLM 排版",
            length=len(text),
            limit=settings.knowledge.markdown_normalize_max_chars,
        )
        return text

    try:
        llm = get_fast_llm()
        result = await asyncio.wait_for(
            llm.ainvoke(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"文档标题：{title or '未命名'}\n"
                            f"来源类型：{source_type}\n\n"
                            f"待整理的 Markdown：\n{text}"
                        ),
                    },
                ]
            ),
            timeout=min(settings.llm.timeout, 90.0),
        )
        content = getattr(result, "content", result)
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        content = _strip_fence(str(content or ""))
        # 明显缩水说明模型可能在总结/截断，保留原文更安全
        if len(content) < max(80, int(len(text) * 0.2)):
            logger.warning(
                "Markdown 整理结果异常偏短，回退原文",
                original=len(text),
                optimized=len(content),
            )
            return text
        return content
    except asyncio.TimeoutError:
        logger.warning("Markdown 整理超时，回退原文")
        return text
    except Exception as exc:
        logger.warning("Markdown 整理失败，回退原文", error=str(exc))
        return text
