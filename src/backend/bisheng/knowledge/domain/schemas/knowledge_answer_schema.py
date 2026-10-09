"""Bounded, stateless knowledge-space answer contract."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

PositiveId = Annotated[StrictInt, Field(gt=0)]


class AnswerSpaceFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge_base_id: PositiveId
    tags: list[StrictStr] = Field(default_factory=list, max_length=20)
    tag_match_mode: Literal["ANY"] = "ANY"

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        normalized = [tag.strip() for tag in tags]
        if any(not tag or len(tag) > 128 for tag in normalized):
            raise ValueError("tags must contain 1 to 128 non-whitespace characters")
        return list(dict.fromkeys(normalized))


class AnswerFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge_base_filters: list[AnswerSpaceFilter] = Field(default_factory=list, max_length=20)


class KnowledgeAnswerReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: StrictStr = Field(min_length=1, max_length=4096)
    knowledge_base_ids: list[PositiveId] = Field(min_length=1, max_length=20)
    model_id: PositiveId
    filters: AnswerFilters | None = None
    top_k: Annotated[StrictInt, Field(ge=1, le=50)] = 10
    max_content: Annotated[StrictInt, Field(ge=1, le=60000)] = 15000

    @field_validator("query")
    @classmethod
    def normalize_query(cls, query: str) -> str:
        query = query.strip()
        if not query:
            raise ValueError("query must not be blank")
        return query

    @field_validator("knowledge_base_ids")
    @classmethod
    def normalize_spaces(cls, ids: list[int]) -> list[int]:
        return sorted(set(ids))

    @model_validator(mode="after")
    def validate_filters(self):
        seen: set[int] = set()
        for item in self.filters.knowledge_base_filters if self.filters else []:
            if item.knowledge_base_id not in self.knowledge_base_ids or item.knowledge_base_id in seen:
                raise ValueError("each filtered space must appear exactly once in the requested scope")
            seen.add(item.knowledge_base_id)
        return self


class KnowledgeAnswerReference(BaseModel):
    knowledge_id: int
    document_id: int
    document_name: str
    document_update_time: str = ""


class KnowledgeAnswerResp(BaseModel):
    answer: str
    has_context: bool
    model_id: int
    references: list[KnowledgeAnswerReference]
