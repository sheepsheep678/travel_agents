"""知识库文件内容抽取：MD/TXT/PDF/图片。

图片优先走 DashScope Qwen-VL，把截图忠实转写成 Markdown；未配置模型时明确报错，
不引入 Tesseract/PaddleOCR 这类重依赖。
"""

import io
import logging
import os
import tempfile
from pathlib import Path

from backend.app.services.config import settings

logger = logging.getLogger(__name__)


class KnowledgeValidationError(Exception):
    """上传内容无法解析/不合法，由 API 层转成 4xx。"""


ALLOWED_EXTENSIONS = {
    ".md": "md",
    ".txt": "txt",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
}


def detect_source_type(filename: str, data: bytes) -> str:
    """扩展名 + 魔数双校验，返回 md/txt/pdf/image。"""
    ext = Path(filename or "").suffix.lower()
    source_type = ALLOWED_EXTENSIONS.get(ext)
    if source_type is None:
        raise KnowledgeValidationError(
            "不支持的文件类型，请上传 MD / TXT / PDF / PNG / JPG / WEBP"
        )

    if source_type == "pdf" and not data.startswith(b"%PDF"):
        raise KnowledgeValidationError("文件内容不是有效的 PDF")
    if ext == ".png" and not data.startswith(b"\x89PNG"):
        raise KnowledgeValidationError("文件内容不是有效的 PNG")
    if ext in (".jpg", ".jpeg") and not data.startswith(b"\xff\xd8"):
        raise KnowledgeValidationError("文件内容不是有效的 JPEG")
    if ext == ".webp" and not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        raise KnowledgeValidationError("文件内容不是有效的 WEBP")

    return source_type


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise KnowledgeValidationError("文本编码无法识别，请使用 UTF-8 或 GB18030")


def _extract_pdf(data: bytes) -> str:
    # 延迟导入：pypdf 是可选依赖，未安装时 API 仍应正常启动。
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise KnowledgeValidationError(
            "PDF 解析依赖 pypdf 未安装，请先执行 pip install pypdf"
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise KnowledgeValidationError(f"PDF 解析失败: {exc}") from exc

    page_count = len(reader.pages)
    if page_count > settings.knowledge_max_pdf_pages:
        raise KnowledgeValidationError(
            f"PDF 页数超过 {settings.knowledge_max_pdf_pages} 页"
        )

    pages = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # 单页损坏不拖垮整篇
            logger.warning("PDF 第 %d 页解析失败: %s", index, exc)
            text = ""
        text = text.strip()
        if text:
            pages.append(f"## 第 {index} 页\n{text}")

    full_text = "\n\n".join(pages).strip()
    if len(full_text) < 20:
        raise KnowledgeValidationError(
            "PDF 没有可用文本层（可能是扫描件），请上传文字版或截图"
        )
    return full_text


def _image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _extract_image(data: bytes) -> str:
    model = settings.knowledge_vlm_model.strip()
    if not model:
        raise KnowledgeValidationError(
            "图片解析未启用：请配置 KNOWLEDGE_VLM_MODEL，或上传文字版"
        )

    try:
        import dashscope
        from dashscope import MultiModalConversation
    except Exception as exc:  # pragma: no cover - 依赖缺失时给出可读错误
        raise KnowledgeValidationError("图片解析依赖 dashscope 未安装") from exc

    dashscope.api_key = settings.openai_api_key
    suffix = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }.get(_image_mime(data), ".png")
    prompt = (
        "你是旅行资料转写助手。请忠实转写图片中的全部文字，保留标题、表格、"
        "列表和“A→B”的路线关系，输出 Markdown。不要总结、不要补全、不要编造；"
        "看不清的内容写 [不清晰]。如果图片中有路线和时长，请保留原始表达。"
    )

    # DashScope 的 MultiModalConversation 不识别 data:image/...;base64，
    # 只识别 http URL / oss:// / 本地文件路径。写临时文件后由 SDK 自动上传成 OSS URL。
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        response = MultiModalConversation.call(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"image": tmp_path},
                        {"text": prompt},
                    ],
                }
            ],
        )
    except Exception as exc:
        raise KnowledgeValidationError(f"图片识别调用失败: {exc}") from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    status_code = getattr(response, "status_code", 200)
    if status_code != 200:
        message = getattr(response, "message", "未知错误")
        raise KnowledgeValidationError(f"图片识别失败: {message}")

    output = getattr(response, "output", None)
    choices = getattr(output, "choices", None) if output else None
    if not choices:
        raise KnowledgeValidationError("图片识别没有返回内容")

    content = getattr(choices[0].message, "content", None)
    if isinstance(content, list):
        text = "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
        )
    else:
        text = str(content or "")

    text = text.strip()
    if not text:
        raise KnowledgeValidationError("图片识别结果为空，请换一张更清晰的图片")
    return text


def extract_content(data: bytes, source_type: str, filename: str = "") -> tuple[str, str]:
    """返回 (文本, 抽取方式)。抽取方式用于 metadata: text/pdf/vlm。"""
    if source_type in ("md", "txt"):
        return _decode_text(data), "text"
    if source_type == "pdf":
        return _extract_pdf(data), "pdf"
    if source_type == "image":
        return _extract_image(data), "vlm"
    raise KnowledgeValidationError(f"未知的文件类型: {source_type}")
