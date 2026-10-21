"""Strict query contract for the new directory, separate from legacy filters."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AuditGroupQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    tenant_id: int | None = Field(default=None, gt=0, le=9223372036854775807)
    user_id: int | None = Field(default=None, gt=0, le=9223372036854775807)
    request_id: str | None = Field(default=None, min_length=1, max_length=36)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=256)
    model_name: str | None = Field(default=None, min_length=1, max_length=2048)
    audit_status: Literal["NORMAL", "ABNORMAL"] | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    cursor: str | None = Field(default=None, max_length=2048)
    limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_range(self):
        start = self.start_at.replace(tzinfo=UTC) if self.start_at and self.start_at.tzinfo is None else self.start_at
        end = self.end_at.replace(tzinfo=UTC) if self.end_at and self.end_at.tzinfo is None else self.end_at
        if start and end and start >= end:
            raise ValueError("Invalid audit time range")
        return self


class AuditTreeQuery(AuditGroupQuery):
    generation: str | None = Field(default=None, min_length=36, max_length=36, pattern="^[0-9a-f-]{36}$")
