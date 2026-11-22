"""知识库文件内容抽取：MD/TXT/PDF/图片。

- PDF：优先 MinerU 云端 Precision API（``mineru-open-sdk`` 的 ``MinerU`` 客户端），
  默认 ``extract(..., ocr=True)`` 开启 OCR；Token 缺失/解析失败时回退 pypdf。
- 图片：优先 DashScope Qwen-VL 转写；VLM 不可用时可选 MinerU OCR 兜底。
"""

import io
import logging
import tempfile
from pathlib import Path

from backend.app.core.config import settings
from backend.app.core.exceptions import ValidationFailedError

logger = logging.getLogger(__name__)


class KnowledgeValidationError(ValidationFailedError):
    """上传内容无法解析/不合法，由全局异常处理器转成 422。"""

    code = "knowledge_validation_failed"


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


def _check_pdf_pages(data: bytes) -> None:
    """用 pypdf 先做页数上限校验，避免 MinerU 解析超大 PDF。"""
    try:
        from pypdf import PdfReader
    except Exception:
        return
    try:
        reader = PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
    except Exception:
        return
    if page_count > settings.knowledge.max_pdf_pages:
        raise KnowledgeValidationError(
            f"PDF 页数超过 {settings.knowledge.max_pdf_pages} 页"
        )


def _extract_with_mineru(
    data: bytes, filename: str = "", suffix: str = ".pdf"
) -> str:
    """调用 MinerU 云端 Precision API 解析文件并返回 Markdown。

    使用 ``mineru-open-sdk`` 的类式接口::

        client = MinerU(token)
        result = client.extract(path, ocr=True, ...)
        markdown = result.markdown

    注意：文件会上传到 mineru.net；Token 从 ``MINERU_TOKEN`` 读取。
    未配置 Token、SDK 未安装或解析失败时返回空串，由调用方回退。
    """
    if not settings.knowledge.mineru_enabled:
        return ""

    token = (settings.knowledge.mineru_token or "").strip()
    if not token:
        logger.warning(
            "MINERU_TOKEN 未配置，跳过 MinerU 云端解析并回退 pypdf；"
            "请到 https://mineru.net/apiManage/token 获取 Token"
        )
        return ""

    try:
        from mineru import MinerU
    except Exception as exc:
        logger.warning(
            "mineru-open-sdk 不可用（请安装 mineru-open-sdk，"
            "不要同时安装本地 mineru 包）: %s",
            exc,
        )
        return ""

    stem = Path(filename or "document").stem or "document"
    suffix = suffix if suffix.startswith(".") else f".{suffix}"

    try:
        with tempfile.TemporaryDirectory(prefix="mineru_") as work_dir:
            input_path = Path(work_dir) / f"{stem}{suffix}"
            input_path.write_bytes(data)

            options: dict = {
                "ocr": settings.knowledge.mineru_ocr,
                "language": settings.knowledge.mineru_language,
                "timeout": settings.knowledge.mineru_timeout,
            }
            if settings.knowledge.mineru_model.strip():
                options["model"] = settings.knowledge.mineru_model.strip()
            if settings.knowledge.mineru_pages.strip():
                options["pages"] = settings.knowledge.mineru_pages.strip()

            logger.info(
                "调用 MinerU 云端 Precision API: model=%s ocr=%s language=%s",
                options.get("model", "auto"),
                options["ocr"],
                options["language"],
            )
            with MinerU(token) as client:
                result = client.extract(str(input_path), **options)

            state = getattr(result, "state", "")
            if state != "done":
                logger.warning(
                    "MinerU 云端任务未完成: state=%s error=%s",
                    state,
                    getattr(result, "error", None),
                )
                return ""
            markdown = (result.markdown or "").strip()

        if not markdown:
            logger.warning("MinerU 云端返回空 Markdown")
            return ""
        logger.info("MinerU 云端解析完成，Markdown 长度 %d", len(markdown))
        return markdown
    except Exception as exc:
        logger.warning("MinerU 云端解析失败，回退其他方式: %s", exc)
        return ""


def _extract_pdf(data: bytes, filename: str = "") -> tuple[str, str]:
    """返回 (文本, 解析方式)；优先 MinerU SDK，失败回退 pypdf。"""
    _check_pdf_pages(data)

    if settings.knowledge.mineru_enabled:
        mineru_text = _extract_with_mineru(data, filename, ".pdf")
        if mineru_text and len(mineru_text) >= 20:
            return mineru_text, "mineru"
        if not settings.knowledge.mineru_fallback:
            raise KnowledgeValidationError("MinerU 解析失败，且未启用回退")

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
    if page_count > settings.knowledge.max_pdf_pages:
        raise KnowledgeValidationError(
            f"PDF 页数超过 {settings.knowledge.max_pdf_pages} 页"
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
    return full_text, "pdf"


def _image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _extract_image(data: bytes) -> str:
    model = settings.knowledge.vlm_model.strip()
    if not model:
        raise KnowledgeValidationError(
            "图片解析未启用：请配置 KNOWLEDGE_VLM_MODEL，或上传文字版"
        )

    try:
        import dashscope
        from dashscope import MultiModalConversation
    except Exception as exc:  # pragma: no cover - 依赖缺失时给出可读错误
        raise KnowledgeValidationError("图片解析依赖 dashscope 未安装") from exc

    dashscope.api_key = settings.llm.api_key
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
    """返回 (文本, 抽取方式)。抽取方式用于 metadata: text/mineru/pdf/vlm。"""
    if source_type in ("md", "txt"):
        return _decode_text(data), "text"
    if source_type == "pdf":
        return _extract_pdf(data, filename)
    if source_type == "image":
        try:
            return _extract_image(data), "vlm"
        except KnowledgeValidationError:
            # VLM 未配置时，若 MinerU 可用则尝试 OCR 兜底
            if settings.knowledge.mineru_enabled:
                suffix = Path(filename or "").suffix or {
                    "image/png": ".png",
                    "image/jpeg": ".jpg",
                    "image/webp": ".webp",
                }.get(_image_mime(data), ".png")
                mineru_text = _extract_with_mineru(data, filename or "image", suffix)
                if mineru_text:
                    return mineru_text, "mineru"
            raise
    raise KnowledgeValidationError(f"未知的文件类型: {source_type}")
