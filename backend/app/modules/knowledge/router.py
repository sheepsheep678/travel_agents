"""知识库路由：用户上传 / 列表 / 删除 + 管理端上传。"""

from __future__ import annotations

import re
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile

from backend.app.core.config import settings
from backend.app.core.deps import get_knowledge_service
from backend.app.core.exceptions import (
    BadRequestError,
    NotFoundError,
    PayloadTooLargeError,
    PermissionDeniedError,
)
from backend.app.modules.knowledge.schemas import (
    KnowledgeConfigResponse,
    KnowledgeDeleteResponse,
    KnowledgeListResponse,
    KnowledgeUploadResponse,
)
from backend.app.modules.knowledge.service import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _validate_user(user_id: str) -> str:
    if not _USER_ID_RE.match(user_id or ""):
        raise BadRequestError("user_id 格式不合法（8-64 位字母、数字、下划线或短横线）")
    return user_id


async def _read_upload(file: Optional[UploadFile]) -> tuple[bytes, str]:
    if file is None:
        return b"", ""
    data = await file.read()
    max_bytes = settings.knowledge.max_file_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise PayloadTooLargeError(f"文件超过 {settings.knowledge.max_file_mb}MB")
    return data, file.filename or ""


async def _ingest_knowledge(
    service: KnowledgeService,
    *,
    user_id: str,
    text: str,
    title: str,
    city: str,
    file: Optional[UploadFile],
    scope: str,
) -> KnowledgeUploadResponse:
    if not text.strip() and file is None:
        raise BadRequestError("请提供文本或文件")
    if len(text) > settings.knowledge.max_text_chars:
        raise PayloadTooLargeError(f"文本超过 {settings.knowledge.max_text_chars} 字")

    data, filename = await _read_upload(file)
    item = await service.ingest(
        user_id=user_id,
        text=text,
        file_data=data or None,
        filename=filename,
        scope=scope,
        title=title,
        city=city,
    )
    return KnowledgeUploadResponse(success=True, message="上传成功", item=item)


@router.post("/upload", response_model=KnowledgeUploadResponse, summary="用户上传知识库")
async def upload_knowledge(
    user_id: str = Form(...),
    text: str = Form(""),
    title: str = Form(""),
    city: str = Form(""),
    file: Optional[UploadFile] = File(None),
    service: KnowledgeService = Depends(get_knowledge_service),
):
    """用户上传：scope=user, owner_id=user_id。"""
    user_id = _validate_user(user_id)
    return await _ingest_knowledge(
        service,
        user_id=user_id,
        text=text,
        title=title,
        city=city,
        file=file,
        scope="user",
    )


@router.get("/list", response_model=KnowledgeListResponse, summary="列出用户知识库")
async def list_knowledge(
    user_id: str = Query(...),
    service: KnowledgeService = Depends(get_knowledge_service),
):
    """列出当前用户上传的文档，只返回预览信息。"""
    user_id = _validate_user(user_id)
    items = await service.list_documents(user_id)
    return KnowledgeListResponse(success=True, items=items)


@router.get("/config", response_model=KnowledgeConfigResponse, summary="知识库上传限制")
async def knowledge_config() -> KnowledgeConfigResponse:
    """返回后端生效的上传上限，前端据此做本地校验与提示。"""
    return KnowledgeConfigResponse(
        max_file_mb=settings.knowledge.max_file_mb,
        max_text_chars=settings.knowledge.max_text_chars,
    )


@router.delete("/{doc_id}", response_model=KnowledgeDeleteResponse, summary="删除用户知识库文档")
async def delete_knowledge(
    doc_id: str,
    user_id: str = Query(...),
    service: KnowledgeService = Depends(get_knowledge_service),
):
    """删除当前用户自己上传的文档。"""
    user_id = _validate_user(user_id)
    deleted = await service.delete_document(doc_id, user_id)
    if not deleted:
        raise NotFoundError("内容不存在或无权删除")
    return KnowledgeDeleteResponse(success=True, message="已删除")


@router.post("/admin/upload", response_model=KnowledgeUploadResponse, summary="管理端上传知识库")
async def admin_upload_knowledge(
    text: str = Form(""),
    title: str = Form(""),
    city: str = Form(""),
    file: Optional[UploadFile] = File(None),
    x_admin_token: str = Header(""),
    service: KnowledgeService = Depends(get_knowledge_service),
):
    """管理端上传：scope=admin, owner_id=admin，需要 X-Admin-Token。"""
    expected = settings.knowledge.admin_token.strip()
    if not expected or not secrets.compare_digest(x_admin_token, expected):
        raise PermissionDeniedError("管理端上传未授权")

    return await _ingest_knowledge(
        service,
        user_id="admin",
        text=text,
        title=title,
        city=city,
        file=file,
        scope="admin",
    )
