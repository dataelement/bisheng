from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class APIAddQAParam(BaseModel):
    question: str
    answer: list[str]
    extra: dict | None = {}


class APIAppendQAParam(BaseModel):
    relative_questions: list[str] = []
    id: str = None


class QueryQAParam(BaseModel):
    timeRange: list[str]


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
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, description="User question")
    knowledge_base_ids: list[int] = Field(
        ..., min_length=1, description="Knowledge base ids to search across"
    )
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
    document_update_time: str = Field(
        default="",
        description="Latest update time of the source document (YYYY-MM-DD HH:mm:ss)",
    )


class RetrieveResp(BaseModel):
    chunks: list[RetrieveChunk]
    total: int
