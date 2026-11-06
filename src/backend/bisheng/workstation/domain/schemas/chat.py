"""Shared daily-chat request models used by v1 and Open API adapters."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator, model_validator


class ToolPayload(BaseModel):
    id: int = 0
    tool_key: str | None = None
    type: str = "tool"


class UseKnowledgeBaseParam(BaseModel):
    personal_knowledge_enabled: bool | None = False
    organization_knowledge_ids: list[int] | None = []
    knowledge_space_ids: list[int] | None = []
    knowledge_space_tag_filters: dict[Annotated[int, Field(gt=0)], Annotated[int, Field(strict=True, gt=0)]] = Field(
        default_factory=dict
    )

    @field_validator("knowledge_space_tag_filters", mode="before")
    @classmethod
    def validate_space_tag_filter_keys(cls, value: Any):
        if value is None:
            return {}
        if isinstance(value, dict) and any(
            isinstance(key, bool) or not (isinstance(key, int) or (isinstance(key, str) and key.isdecimal()))
            for key in value
        ):
            raise ValueError("Knowledge space ids must be positive integers")
        return value

    @model_validator(mode="after")
    def validate_selected_space_tag_filters(self):
        if not set(self.knowledge_space_tag_filters).issubset(self.knowledge_space_ids or []):
            raise ValueError("Tag filters must belong to selected knowledge spaces")
        return self

    @field_validator("organization_knowledge_ids", mode="before")
    @classmethod
    def convert_organization_knowledge_ids(cls, value: Any):
        if len(value) > 50:
            raise ValueError("Can only be used up to 50 organization knowledge base")
        return value

    @field_validator("knowledge_space_ids", mode="before")
    @classmethod
    def convert_knowledge_space_ids(cls, value: Any):
        if len(value) > 50:
            raise ValueError("Can only be used up to 50 knowledge space")
        return value


class APIChatCompletion(BaseModel):
    clientTimestamp: str
    conversationId: str | None = None
    error: bool | None = False
    generation: str | None = ""
    isCreatedByUser: bool | None = False
    isContinued: bool | None = False
    model: str
    text: str | None = ""
    tools: list[ToolPayload] | None = None
    task_mode: bool | None = False
    skills: list[str] | None = None
    skill_ids: list[int] | None = None
    use_knowledge_base: UseKnowledgeBaseParam | None = None
    files: list[dict] | None = None
    search_enabled: bool | None = False
    parentMessageId: str | None = None
    overrideParentMessageId: str | None = None
    responseMessageId: str | None = None

    @field_validator("parentMessageId", "overrideParentMessageId", "responseMessageId", mode="before")
    @classmethod
    def coerce_optional_str_id(cls, value: Any):
        if value is None or isinstance(value, str):
            return value
        return str(value)
