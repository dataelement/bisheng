"""Request and view contracts for task mode over the Open API (F073)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bisheng.open_api.domain.schemas.workstation import OpenDailyToolPayload
from bisheng.workstation.domain.schemas.chat import APIChatCompletion, UseKnowledgeBaseParam

TASK_TEXT_MAX_LENGTH = 20000
TASK_INSTRUCTIONS_MAX_LENGTH = 4000
TASK_KNOWLEDGE_MAX_ITEMS = 50
TASK_SKILLS_MAX_ITEMS = 50
TASK_FILES_MAX_ITEMS = 50


class OpenTaskFileRef(BaseModel):
    """One attachment, exactly as ``POST /api/v2/knowledge/upload`` returned it."""

    model_config = ConfigDict(extra="ignore")

    file_path: str = Field(min_length=1)
    file_name: str = Field(min_length=1)


class OpenTaskSubmitReq(BaseModel):
    """Task-mode submission. Same endpoint as daily chat, told apart by ``run_mode``."""

    model_config = ConfigDict(extra="forbid")

    run_mode: Literal["task"]
    execution: Literal["async"]
    clientTimestamp: str
    text: str = Field(min_length=1, max_length=TASK_TEXT_MAX_LENGTH)
    instructions: str | None = Field(default=None, max_length=TASK_INSTRUCTIONS_MAX_LENGTH)
    model: str = Field(min_length=1)
    skills: list[str] | None = Field(default=None, max_length=TASK_SKILLS_MAX_ITEMS)
    tools: list[OpenDailyToolPayload] | None = None
    knowledge_ids: list[int] | None = Field(default=None, max_length=TASK_KNOWLEDGE_MAX_ITEMS)
    knowledge_space_ids: list[int] | None = Field(default=None, max_length=TASK_KNOWLEDGE_MAX_ITEMS)
    files: list[OpenTaskFileRef] | None = Field(default=None, max_length=TASK_FILES_MAX_ITEMS)

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value

    @field_validator("skills")
    @classmethod
    def dedupe_skills(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(name for name in value if name))

    def file_refs(self) -> list[dict]:
        """The shape ``TempUploadService.assert_owned_references`` checks."""

        return [{"file_path": ref.file_path, "file_name": ref.file_name} for ref in self.files or []]

    def to_internal(self) -> APIChatCompletion:
        """Map onto the shared request. Every attachment gets a fresh ``file_id``:
        the linsight submit mapping silently drops entries without one."""

        files = [
            {
                "file_id": uuid4().hex,
                "file_name": ref.file_name,
                "filepath": ref.file_path,
                "parsing_status": "completed",
            }
            for ref in self.files or []
        ]
        return APIChatCompletion.model_validate(
            {
                "clientTimestamp": self.clientTimestamp,
                "conversationId": None,
                "model": self.model,
                "text": self.text,
                "task_mode": True,
                "skills": self.skills or None,
                "tools": [tool.model_dump() for tool in self.tools or []] or None,
                "use_knowledge_base": UseKnowledgeBaseParam(
                    personal_knowledge_enabled=False,
                    organization_knowledge_ids=list(self.knowledge_ids or []),
                    knowledge_space_ids=list(self.knowledge_space_ids or []),
                ),
                "files": files or None,
            }
        )


class OpenTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    # Reserved: API-submitted runs never ask the user (design decision 7). Kept
    # in the enum so adding it later does not change the contract (spec AC-27).
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


class OpenTaskSubmitted(BaseModel):
    task_id: str
    status: OpenTaskStatus
    queue_position: int | None = None


class OpenTaskProgress(BaseModel):
    done: int
    total: int


class OpenTaskFailure(BaseModel):
    category: str
    message: str | None = None


class OpenTaskFile(BaseModel):
    file_id: str
    file_name: str
    file_type: str
    size: int | None = None
    primary: bool = False


class OpenTaskUnavailableDeliverable(BaseModel):
    file_name: str
    reason: Literal["not_generated", "invalid_format"]


class OpenTaskAttachmentIssue(BaseModel):
    file_name: str
    reason: str


class OpenTaskResult(BaseModel):
    answer: str
    files: list[OpenTaskFile] = []
    unavailable_deliverables: list[OpenTaskUnavailableDeliverable] = []
    attachments: list[OpenTaskAttachmentIssue] = []


class OpenTaskView(BaseModel):
    task_id: str
    status: OpenTaskStatus
    queue_position: int | None = None
    progress: OpenTaskProgress | None = None
    partial: bool | None = None
    failure: OpenTaskFailure | None = None
    result: OpenTaskResult | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OpenTaskSkill(BaseModel):
    name: str
    display_name: str
    description: str | None = None


__all__ = [
    "OpenTaskAttachmentIssue",
    "OpenTaskFailure",
    "OpenTaskFile",
    "OpenTaskFileRef",
    "OpenTaskProgress",
    "OpenTaskResult",
    "OpenTaskSkill",
    "OpenTaskStatus",
    "OpenTaskSubmitReq",
    "OpenTaskSubmitted",
    "OpenTaskUnavailableDeliverable",
    "OpenTaskView",
]
