from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from bisheng.knowledge.domain.models.knowledge import KnowledgeRead
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

ExternalUserId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class APIAddQAParam(BaseModel):
    question: str
    answer: list[str]
    extra: dict | None = {}


class APIAppendQAParam(BaseModel):
    relative_questions: list[str] = []
    id: str = None


class QueryQAParam(BaseModel):
    timeRange: list[str]


class FilelibKnowledgeRead(KnowledgeRead):
    """Filelib 知识资源列表项, 知识空间额外返回门户层级。"""

    space_level: KnowledgeSpaceLevelEnum | None = None


class KnowledgeBaseFilter(BaseModel):
    """Per-knowledge-base filter applied when retrieving chunks."""

    knowledge_base_id: int = Field(..., description="Must appear in knowledge_base_ids")
    tags: list[str] = Field(
        default_factory=list,
        description="Tag names defined under this knowledge base used to narrow files",
    )
    tag_match_mode: Literal["ANY", "ALL"] = Field(
        default="ANY",
        description="ANY = file matches any tag; ALL is reserved for future use",
    )


class RetrieveFilters(BaseModel):
    knowledge_base_filters: list[KnowledgeBaseFilter] = Field(default_factory=list)


class RetrieveReq(BaseModel):
    external_id: ExternalUserId | None = Field(
        default=None,
        description="External user ID used for permission and data scope",
    )
    query: str = Field(..., min_length=1, description="User question")
    knowledge_base_ids: list[int] = Field(..., min_length=1, description="Knowledge base ids to search across")
    filters: RetrieveFilters | None = None
    top_k: int = Field(default=10, ge=1, le=200, description="Max chunks to return")
    max_content: int = Field(
        default=15000,
        ge=1,
        description="Per-knowledge-base content length cap during merge",
    )


class RetrieveChunk(BaseModel):
    content: str
    knowledge_id: int
    document_id: int
    document_name: str
    chunk_index: int
    source_url: str = ""
    source_full_url: str = ""


class RetrieveResp(BaseModel):
    chunks: list[RetrieveChunk]
    total: int


class FileDetailFile(BaseModel):
    id: int
    knowledge_id: int
    file_encoding: str
    file_name: str
    file_size: int | None = None
    status: int | None = None
    update_time: str = ""
    is_primary: bool
    document_type: str
    categoryID: str
    categoryGroupClassCode: str
    docTypeCode: str


class FileDetailResp(BaseModel):
    file: FileDetailFile | None = None
    content: str = ""
    chunk_count: int = 0
