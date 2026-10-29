"""Strict query contract for the new directory, separate from legacy filters."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bisheng.dsh.domain.schemas.content_safety import ContentSafetyState, SensitiveDirection
from bisheng.dsh.domain.schemas.model_audit import AuditDTO


class AuditGroupQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    tenant_id: int | None = Field(default=None, gt=0, le=9223372036854775807)
    user_id: int | None = Field(default=None, gt=0, le=9223372036854775807)
    request_id: str | None = Field(default=None, min_length=1, max_length=36)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=256)
    model_name: str | None = Field(default=None, min_length=1, max_length=2048)
    audit_status: Literal["NORMAL", "ABNORMAL"] | None = None
    has_sensitive_hit: bool | None = None
    sensitive_direction: SensitiveDirection | None = None
    content_safety_state: ContentSafetyState | None = None
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


class AuditQueryReadiness(AuditDTO):
    status_ready: bool
    name_ready: bool
    indexing_pending: bool | None = None
    coverage: str = "OBSERVABLE_ESTIMATE"
    hierarchy_available: bool = False
    hierarchy_ready: bool = False
    generation: str | None = None
    phase: Literal["PREPARING", "READY", "UPDATING", "FAILED"] | None = None
    summary_ready: bool = False
    refresh_required: bool = False
    safety_ready: bool = False
    safety_summary_version: int = Field(default=0, ge=0)
    safety_summary_as_of: datetime | None = None


class AuditConversation(AuditDTO):
    conversation_key: str
    user_id: int
    conversation_id: str
    user_name: str | None = None
    conversation_title: str | None = None
    title_event_seq: int | None = None
    listed_at: datetime
    last_request_at: datetime
    updated_at: datetime
    request_count: int = Field(ge=0)
    abnormal_count: int = Field(ge=0)
    has_sensitive_hit: bool = False
    sensitive_hit_count: int = Field(default=0, ge=0)
    matching_sensitive_hit_count: int | None = Field(default=None, ge=0)
    summary_scope: Literal["ALL_INDEXED_REQUESTS"] = "ALL_INDEXED_REQUESTS"
    request_filter_scope: Literal["MATCHING_REQUESTS"] = "MATCHING_REQUESTS"


class AuditTreeSummary(AuditDTO):
    ready: bool
    request_count: int | None = Field(ge=0)
    abnormal_count: int | None = Field(ge=0)
    known_abnormal: bool
    sensitive_hit_count: int | None = Field(default=None, ge=0)
    has_sensitive_hit: bool = False
    safety_ready: bool = False


class AuditTreeNode(AuditConversation):
    generation: str
    parent_key: str
    root_key: str
    relation_state: Literal[
        "MAIN",
        "UNKNOWN",
        "LINKED",
        "MISSING_PARENT",
        "PARENT_UNAVAILABLE",
        "SELF_REFERENCE",
        "CYCLE",
        "CONFLICT",
        "DEPTH_LIMIT",
    ]
    has_children: bool
    match_scope: Literal["SELF", "DESCENDANT", "BOTH"]
    own_summary: AuditTreeSummary
    branch_summary: AuditTreeSummary
    summary_as_of: datetime | None = None


class AuditGroupPage(AuditDTO):
    items: list[AuditConversation]
    next_cursor: str | None = None
    scan_limited: bool = False
    progress: AuditQueryReadiness


class AuditTreePage(AuditGroupPage):
    items: list[AuditTreeNode]
