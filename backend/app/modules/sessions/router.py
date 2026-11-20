"""会话路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.app.core.deps import get_session_service
from backend.app.modules.sessions.schemas import (
    SessionCreateRequest,
    SessionDeleteResponse,
    SessionEnsureRequest,
    SessionListResponse,
    SessionResponse,
    SessionUpdateRequest,
)
from backend.app.modules.sessions.service import SessionService

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/ensure", response_model=SessionResponse, summary="校验或创建会话")
async def ensure_session(
    payload: SessionEnsureRequest,
    service: SessionService = Depends(get_session_service),
):
    """前端提交 user_id + session_id；存在且归属正确则返回，否则新建。"""
    session = await service.ensure_session(
        payload.user_id,
        payload.session_id,
        title=payload.title,
        city=payload.city,
    )
    return SessionResponse(session=session)


@router.post("", response_model=SessionResponse, summary="创建会话")
async def create_session(
    payload: SessionCreateRequest,
    service: SessionService = Depends(get_session_service),
):
    session = await service.create_session(
        payload.user_id, title=payload.title, city=payload.city
    )
    return SessionResponse(session=session)


@router.get("", response_model=SessionListResponse, summary="会话列表")
async def list_sessions(
    user_id: str = Query(...),
    service: SessionService = Depends(get_session_service),
):
    sessions = await service.list_sessions(user_id)
    return SessionListResponse(sessions=sessions)


@router.get("/{session_id}", response_model=SessionResponse, summary="会话详情（含消息）")
async def get_session(
    session_id: str,
    user_id: str = Query(...),
    service: SessionService = Depends(get_session_service),
):
    session = await service.get_session(session_id, user_id)
    return SessionResponse(session=session)


@router.patch("/{session_id}", response_model=SessionResponse, summary="更新会话标题 / 城市")
async def update_session(
    session_id: str,
    payload: SessionUpdateRequest,
    service: SessionService = Depends(get_session_service),
):
    session = await service.update_session(
        session_id,
        payload.user_id,
        title=payload.title,
        city=payload.city,
    )
    return SessionResponse(session=session)


@router.delete("/{session_id}", response_model=SessionDeleteResponse, summary="删除会话")
async def delete_session(
    session_id: str,
    user_id: str = Query(...),
    service: SessionService = Depends(get_session_service),
):
    await service.delete_session(session_id, user_id)
    return SessionDeleteResponse(message="已删除")
