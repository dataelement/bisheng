"""Shared daily-chat request models used by v1 and Open API adapters."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class ToolPayload(BaseModel):
    id: int = 0
    tool_key: str | None = None
    type: str = "tool"


class UseKnowledgeBaseParam(BaseModel):
    personal_knowledge_enabled: bool | None = False
    organization_knowledge_ids: list[int] | None = []
    knowledge_space_ids: list[int] | None = []
    # per-space FIXED tag references (space id -> tag ref id). Typed as a plain
    # mapping so every existing reader keeps its shape; whether the *request*
    # actually declared the field is exposed by ``tag_scope_recorded`` below.
    knowledge_space_tag_filters: dict[Annotated[int, Field(gt=0)], Annotated[int, Field(strict=True, gt=0)]] = Field(
        default_factory=dict
    )

    @property
    def tag_scope_recorded(self) -> bool:
        """True when this request declared its tag scope.

        An omitted ``knowledge_space_tag_filters`` (an older client, or an older
        round reloaded from history) is NOT "the user pinned no tag": it means the
        scope was never recorded. Both states serialize to ``{}`` for legacy
        readers, so the marker has to be read from the request itself.
        """
        return "knowledge_space_tag_filters" in self.model_fields_set or bool(self.knowledge_space_tag_filters)

    @field_validator("knowledge_space_tag_filters", mode="before")
    @classmethod
    def validate_space_tag_filter_keys(cls, value: Any):
        if value is None:
            raise ValueError("Provide an explicit tag map, or omit the field for a legacy request")
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
    project_id: UUID | None = None
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
    # F026 AC-27: a regenerate must reuse the material scope recorded on the
    # ORIGINAL round, not the picker's current state. The client marks it with
    # ``isRegenerate`` and names the question row it regenerates in ``messageId``
    # (``overrideParentMessageId`` is the legacy spelling).
    isRegenerate: bool | None = False
    messageId: str | None = None
    # Explicit "use the current materials and ask again": the ONLY case that takes
    # the current picker for a regenerate. Anything else keeps the original scope.
    useCurrentMaterials: bool | None = False
    overrideParentMessageId: str | None = None
    responseMessageId: str | None = None

    @model_validator(mode="after")
    def validate_project_intent(self):
        if self.project_id is not None and self.conversationId:
            raise ValueError("Project intent is only accepted for a new conversation")
        return self

    @field_validator("parentMessageId", "overrideParentMessageId", "responseMessageId", "messageId", mode="before")
    @classmethod
    def coerce_optional_str_id(cls, value: Any):
        if value is None or isinstance(value, str):
            return value
        return str(value)

    @property
    def regenerate_message_id(self) -> str | None:
        """Server id of the question row this turn regenerates, if any.

        Only a digits-only id can name a stored row; the client's optimistic
        temporary id (``"user-…"``) is not a regeneration target.
        """
        if not self.isRegenerate:
            return None
        candidate = self.messageId or self.overrideParentMessageId
        if isinstance(candidate, str) and candidate.isdigit():
            return candidate
        return None
