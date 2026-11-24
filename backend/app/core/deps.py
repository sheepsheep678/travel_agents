"""FastAPI 依赖注入：数据库会话与业务 service。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.modules.chat.service import ChatService
from backend.app.modules.knowledge.service import KnowledgeService
from backend.app.modules.memory.service import MemoryService
from backend.app.modules.sessions.service import SessionService
from backend.app.modules.trip.service import TripService

DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_session_service(db: DbSession) -> SessionService:
    return SessionService(db)


def get_knowledge_service(db: DbSession) -> KnowledgeService:
    return KnowledgeService(db)


def get_trip_service(db: DbSession) -> TripService:
    return TripService(db)


def get_chat_service(db: DbSession) -> ChatService:
    return ChatService(db)


def get_memory_service(db: DbSession) -> MemoryService:
    return MemoryService(db)


SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
KnowledgeServiceDep = Annotated[KnowledgeService, Depends(get_knowledge_service)]
TripServiceDep = Annotated[TripService, Depends(get_trip_service)]
ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
MemoryServiceDep = Annotated[MemoryService, Depends(get_memory_service)]
