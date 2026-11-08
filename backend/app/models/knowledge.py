"""知识库上传的请求/响应模型。"""

from typing import List, Optional

from pydantic import BaseModel, Field


class KnowledgeItem(BaseModel):
    """一条已入库的知识文档（按 doc_id 聚合后的展示信息）。"""

    doc_id: str
    title: str
    preview: str = ""
    source_type: str = "txt"
    chunk_count: int = 1
    city: Optional[str] = ""
    source: Optional[str] = ""
    created_at: str = ""
    scope: Optional[str] = "user"


class KnowledgeUploadResponse(BaseModel):
    success: bool
    message: str = ""
    item: Optional[KnowledgeItem] = None


class KnowledgeListResponse(BaseModel):
    success: bool = True
    items: List[KnowledgeItem] = Field(default_factory=list)


class KnowledgeDeleteResponse(BaseModel):
    success: bool = True
    message: str = ""
