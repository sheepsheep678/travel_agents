"""知识库上传 API：用户会话级上传 + 管理端上传。"""

import asyncio
import logging
import re
import secrets
from functools import partial
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile

from backend.app.models.knowledge import (
    KnowledgeDeleteResponse,
    KnowledgeListResponse,
    KnowledgeUploadResponse,
)
from backend.app.services.config import settings
from backend.app.services.knowledge_extractors import KnowledgeValidationError
from backend.app.services.knowledge_service import (
    delete_document,
    ingest,
    list_documents,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _validate_session(session_id: str) -> str:
    if not _SESSION_RE.match(session_id or ""):
        raise HTTPException(
            status_code=400,
            detail="session_id 格式不合法（8-64 位字母、数字、下划线或短横线）",
        )
    return session_id


async def _read_upload(file: Optional[UploadFile]) -> tuple[bytes, str]:
    if file is None:
        return b"", ""
    data = await file.read()
    max_bytes = settings.knowledge_max_file_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {settings.knowledge_max_file_mb}MB",
        )
    return data, file.filename or ""


@router.post("/upload", response_model=KnowledgeUploadResponse)
async def upload_knowledge(
    session_id: str = Form(...),
    text: str = Form(""),
    title: str = Form(""),
    city: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """用户上传：scope=user, owner_id=session_id。"""
    session_id = _validate_session(session_id)
    if not text.strip() and file is None:
        raise HTTPException(status_code=400, detail="请提供文本或文件")
    if len(text) > settings.knowledge_max_text_chars:
        raise HTTPException(
            status_code=413,
            detail=f"文本超过 {settings.knowledge_max_text_chars} 字",
        )

    data, filename = await _read_upload(file)
    try:
        item = await asyncio.to_thread(
            partial(
                ingest,
                text=text,
                file_data=data or None,
                filename=filename,
                session_id=session_id,
                scope="user",
                title=title,
                city=city,
            )
        )
    except KnowledgeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("知识库上传失败")
        raise HTTPException(status_code=500, detail=f"入库失败: {exc}") from exc

    return KnowledgeUploadResponse(success=True, message="上传成功", item=item)


@router.get("/list", response_model=KnowledgeListResponse)
async def list_knowledge(session_id: str = Query(...)):
    """列出当前会话上传的文档，只返回预览信息。"""
    session_id = _validate_session(session_id)
    try:
        items = await asyncio.to_thread(list_documents, session_id)
    except Exception as exc:
        logger.exception("知识库列表读取失败")
        raise HTTPException(status_code=500, detail=f"读取失败: {exc}") from exc
    return KnowledgeListResponse(success=True, items=items)


@router.delete("/{doc_id}", response_model=KnowledgeDeleteResponse)
async def delete_knowledge(doc_id: str, session_id: str = Query(...)):
    """删除当前会话自己上传的文档。"""
    session_id = _validate_session(session_id)
    try:
        deleted = await asyncio.to_thread(delete_document, doc_id, session_id)
    except Exception as exc:
        logger.exception("知识库删除失败")
        raise HTTPException(status_code=500, detail=f"删除失败: {exc}") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="内容不存在或无权删除")
    return KnowledgeDeleteResponse(success=True, message="已删除")


@router.post("/admin/upload", response_model=KnowledgeUploadResponse)
async def admin_upload_knowledge(
    text: str = Form(""),
    title: str = Form(""),
    city: str = Form(""),
    file: Optional[UploadFile] = File(None),
    x_admin_token: str = Header(""),
):
    """管理端上传：scope=admin, owner_id=admin，需要 X-Admin-Token。"""
    expected = settings.knowledge_admin_token.strip()
    if not expected or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=403, detail="管理端上传未授权")

    if not text.strip() and file is None:
        raise HTTPException(status_code=400, detail="请提供文本或文件")
    if len(text) > settings.knowledge_max_text_chars:
        raise HTTPException(
            status_code=413,
            detail=f"文本超过 {settings.knowledge_max_text_chars} 字",
        )

    data, filename = await _read_upload(file)
    try:
        item = await asyncio.to_thread(
            partial(
                ingest,
                text=text,
                file_data=data or None,
                filename=filename,
                session_id="admin",
                scope="admin",
                title=title,
                city=city,
            )
        )
    except KnowledgeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("管理端知识库上传失败")
        raise HTTPException(status_code=500, detail=f"入库失败: {exc}") from exc

    return KnowledgeUploadResponse(success=True, message="上传成功", item=item)
