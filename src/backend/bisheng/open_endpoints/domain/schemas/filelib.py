from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class APIAddQAParam(BaseModel):
    question: str
    answer: List[str]
    extra: Optional[Dict] = {}


class APIAppendQAParam(BaseModel):
    relative_questions: List[str] = []
    id: str = None


class QueryQAParam(BaseModel):
    timeRange: List[str]


class KnowledgeBaseFilter(BaseModel):
    """Per-knowledge-base filter applied when retrieving chunks."""

    knowledge_base_id: int = Field(..., description="Must appear in knowledge_base_ids")
    tags: List[str] = Field(
        default_factory=list,
        description="Tag names defined under this knowledge base used to narrow files",
    )
    tag_match_mode: Literal["ANY", "ALL"] = Field(
        default="ANY",
        description="ANY = file matches any tag; ALL is reserved for future use",
    )


class RetrieveFilters(BaseModel):
    knowledge_base_filters: List[KnowledgeBaseFilter] = Field(default_factory=list)


class RetrieveReq(BaseModel):
    query: str = Field(..., min_length=1, description="User question")
    knowledge_base_ids: List[int] = Field(
        ..., min_length=1, description="Knowledge base ids to search across"
    )
    filters: Optional[RetrieveFilters] = None
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


class RetrieveResp(BaseModel):
    chunks: List[RetrieveChunk]
    total: int
