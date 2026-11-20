"""会话模块的请求 / 响应模型。"""

from typing import List, Optional

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    user_id: str = Field(..., description="浏览器匿名用户 ID")
    title: str = Field(default="", description="会话标题")
    city: str = Field(default="", description="目的地城市")


class SessionEnsureRequest(BaseModel):
    user_id: str = Field(..., description="浏览器匿名用户 ID")
    session_id: Optional[str] = Field(default=None, description="待校验的会话 ID；为空则新建")
    title: str = Field(default="", description="新建会话时使用的标题")
    city: str = Field(default="", description="新建会话时使用的城市")


class SessionUpdateRequest(BaseModel):
    user_id: str
    title: Optional[str] = None
    city: Optional[str] = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    status: str = "done"


class SessionOut(BaseModel):
    id: str
    user_id: str
    title: str = ""
    city: str = ""
    created_at: str
    updated_at: str
    messages: List[MessageOut] = Field(default_factory=list)


class SessionResponse(BaseModel):
    success: bool = True
    session: SessionOut


class SessionListResponse(BaseModel):
    success: bool = True
    sessions: List[SessionOut] = Field(default_factory=list)


class SessionDeleteResponse(BaseModel):
    success: bool = True
    message: str = ""


class UserEnsureRequest(BaseModel):
    user_id: str


class UserOut(BaseModel):
    id: str


class UserResponse(BaseModel):
    success: bool = True
    user: UserOut
