"""Narrow request contract for daily workstation chat over Open API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bisheng.workstation.domain.schemas.chat import APIChatCompletion


class OpenDailyToolPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = 0
    tool_key: str | None = None
    type: Literal["tool"] = "tool"


class OpenDailyChatCompletionReq(BaseModel):
    """Current APIChatCompletion minus task and knowledge-base selectors."""

    model_config = ConfigDict(extra="forbid")

    # Optional branch selector. The endpoint sends run_mode="task" to the task
    # model; any other value fails here and the v2 handler answers 26017.
    run_mode: Literal["daily"] = Field(
        default="daily",
        description='Run mode. Omit it or send "daily" for daily chat; send "task" for the task-mode body.',
    )
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
    files: list[dict] | None = Field(
        default=None,
        description=(
            "Attachments. Each item carries the uploaded file URL in filepath; file_path is accepted as an alias "
            "(the name used by task mode and the upload response). If both are sent, they must be equal."
        ),
    )
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

    @field_validator("files")
    @classmethod
    def normalize_file_path_alias(cls, value: list[dict] | None) -> list[dict] | None:
        """Fold the task-mode key ``file_path`` into ``filepath``.

        The model input reads only ``filepath``. Without this fold, a
        ``file_path`` attachment passed the ownership check but the model never
        saw it. After the fold, the ownership check and the model read one value.
        """
        if value is None:
            return None
        normalized = []
        for item in value:
            if "file_path" not in item:
                normalized.append(item)
                continue
            primary = item.get("filepath")
            alias = item.get("file_path")
            if primary not in (None, "") and alias not in (None, "") and primary != alias:
                raise ValueError("files item has different filepath and file_path; send only filepath")
            folded = {key: val for key, val in item.items() if key != "file_path"}
            folded["filepath"] = primary if primary not in (None, "") else alias
            normalized.append(folded)
        return normalized

    def to_internal(self) -> APIChatCompletion:
        payload = self.model_dump(exclude={"run_mode"})
        payload["tools"] = [tool.model_dump() for tool in self.tools or []] or None
        payload["task_mode"] = False
        payload["use_knowledge_base"] = None
        return APIChatCompletion.model_validate(payload)
