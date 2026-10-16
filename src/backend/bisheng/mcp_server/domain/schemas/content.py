from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field

from bisheng.mcp_server.domain.schemas.browse import Cursor, ResourceId, StrictRequest
from bisheng.open_endpoints.domain.schemas.filelib import KnowledgeBaseFilter, RetrieveFilters

MaxChars = Annotated[int, Field(strict=True, ge=1, le=50000)]


class McpKnowledgeBaseFilter(KnowledgeBaseFilter):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    knowledge_base_id: ResourceId


class McpRetrieveFilters(RetrieveFilters):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    knowledge_base_filters: list[McpKnowledgeBaseFilter] = Field(default_factory=list, max_length=20)


class FileDetailRequest(StrictRequest):
    knowledge_id: ResourceId
    file_id: ResourceId
    include_content: bool = Field(default=True, strict=True)
    content_format: Literal["text", "markdown"] = "text"
    max_chars: MaxChars = 20000
    cursor: Cursor | None = None


class FileSourceRequest(StrictRequest):
    knowledge_id: ResourceId
    file_id: ResourceId
    source_type: Literal["auto", "preview", "original"] = "auto"


class FileDetailResponse(StrictRequest):
    file: dict[str, Any]
    content: str = ""
    content_ready: bool
    content_format: Literal["text", "markdown"] = "text"
    content_version: str | None = None
    has_more: bool = False
    next_cursor: str | None = None


class FileSourceResponse(StrictRequest):
    file_id: int
    knowledge_id: int
    preview_url: str = ""
    original_url: str = ""
    expires_at: str | None = None
    original_unavailable_reason: str | None = None
