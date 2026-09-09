"""Narrow request contract for daily workstation chat over Open API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from bisheng.workstation.domain.schemas.chat import APIChatCompletion


class OpenDailyToolPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = 0
    tool_key: str | None = None
    type: Literal["tool"] = "tool"


class OpenDailyChatCompletionReq(BaseModel):
    """Current APIChatCompletion minus task and knowledge-base selectors."""

    model_config = ConfigDict(extra="forbid")

    clientTimestamp: str
    conversationId: str | None = None
    error: bool | None = False
    generation: str | None = ""
    isCreatedByUser: bool | None = False
    isContinued: bool | None = False
    model: str
    text: str | None = ""
    tools: list[OpenDailyToolPayload] | None = None
    skills: list[str] | None = None
    files: list[dict] | None = None
    search_enabled: bool | None = False
    parentMessageId: str | None = None
    overrideParentMessageId: str | None = None
    responseMessageId: str | None = None

    @field_validator("parentMessageId", "overrideParentMessageId", "responseMessageId", mode="before")
    @classmethod
    def coerce_optional_str_id(cls, value):
        if value is None or isinstance(value, str):
            return value
        return str(value)

    def to_internal(self) -> APIChatCompletion:
        payload = self.model_dump()
        payload["tools"] = [tool.model_dump() for tool in self.tools or []] or None
        payload["task_mode"] = False
        payload["use_knowledge_base"] = None
        return APIChatCompletion.model_validate(payload)
