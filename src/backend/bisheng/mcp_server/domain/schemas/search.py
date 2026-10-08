from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from bisheng.open_endpoints.domain.schemas.filelib import RetrieveFilters

SearchQuery = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
KnowledgeId = Annotated[int, Field(strict=True, gt=0)]
KnowledgeIds = Annotated[list[KnowledgeId], Field(min_length=1, max_length=20)]
TopK = Annotated[int, Field(strict=True, ge=1, le=50)]
MaxContent = Annotated[int, Field(strict=True, ge=1, le=15000)]


class McpSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: SearchQuery
    knowledge_base_ids: KnowledgeIds
    top_k: TopK = 5
    max_content: MaxContent = 15000
    filters: RetrieveFilters | None = None
