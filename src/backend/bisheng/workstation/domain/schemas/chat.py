"""Shared daily-chat request models used by v1 and Open API adapters."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_validator


class ToolPayload(BaseModel):
    id: int = 0
    tool_key: str | None = None
    type: str = "tool"


class UseKnowledgeBaseParam(BaseModel):
    personal_knowledge_enabled: bool | None = False
    organization_knowledge_ids: list[int] | None = []
    knowledge_space_ids: list[int] | None = []

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

