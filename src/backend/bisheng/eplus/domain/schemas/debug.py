"""Credential-free contracts for the opt-in robot debug service."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bisheng.assistant.domain.schemas.execution import AssistantRobotScope


class DebugHistoryTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4096)
    answer: str = Field(min_length=1, max_length=16000)


class DebugRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4096)
    test_user_id: int = Field(gt=0, strict=True)
    history: list[DebugHistoryTurn] = Field(default_factory=list, max_length=20)

    @field_validator("query", mode="before")
    @classmethod
    def strip_query(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def limit_history(self):
        if sum(len(t.question) + len(t.answer) for t in self.history) > 64000:
            raise ValueError("test history exceeds 64000 characters")
        return self


@dataclass(frozen=True)
class DebugContext:
    tenant_id: int
    operator_id: int
    test_user_id: int
    test_user_name: str
    external_user_id: str
    assistant: Any
    robot_scope: AssistantRobotScope
    bot_id: str
    spaces: tuple[dict, ...]

    def public_view(self) -> dict:
        return {
            "assistant_id": str(self.assistant.id),
            "assistant_name": self.assistant.name,
            "configured_model_id": str(self.assistant.model_name),
            "bot_id": self.bot_id,
            "test_user_id": self.test_user_id,
            "test_user_name": self.test_user_name,
            "external_identity_available": bool(self.external_user_id),
            "space_ids": list(self.robot_scope.space_ids),
            "spaces": list(self.spaces),
            "scope_version": self.robot_scope.scope_version,
        }
