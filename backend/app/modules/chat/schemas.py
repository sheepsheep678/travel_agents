"""对话模块的请求模型与 SSE 事件类型。"""

from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(..., description="浏览器匿名用户 ID")
    session_id: str = Field(..., description="服务端会话 ID")
    message: str = Field(default="", description="用户消息")
    city: Optional[str] = Field(default=None, description="当前对话涉及的城市")
    regenerate: bool = Field(
        default=False,
        description="重新生成：不重复写入用户消息，并删除最后一条助手回复",
    )


class ChatResumeRequest(BaseModel):
    """断线续传：按会话补发已生成但客户端未收到的 token。"""

    user_id: str = Field(..., description="浏览器匿名用户 ID")
    session_id: str = Field(..., description="服务端会话 ID")
    offset: int = Field(default=0, ge=0, description="客户端已收到的字符数")


class ChatCancelRequest(BaseModel):
    """取消正在后台生成的对话回复。"""

    user_id: str = Field(..., description="浏览器匿名用户 ID")
    session_id: str = Field(..., description="服务端会话 ID")
