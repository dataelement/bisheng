"""Audit management DTOs; body data never belongs to metadata responses."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bisheng.dsh.domain.schemas.content_safety import (
    ContentSafetyState,
    SafetyDetailsStatus,
    StageResults,
    StageVersions,
)

AuditMode = Literal["OFF", "METADATA", "CONTENT"]
ModelResult = Literal["RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"]
ResponseResult = Literal["RUNNING", "COMPLETED", "ERROR", "INTERRUPTED", "UNKNOWN"]
UsageSettlement = Literal["PENDING", "SETTLED", "USAGE_UNKNOWN", "UNCERTAIN"]
ContentStatus = Literal["PENDING", "COMPLETE", "PARTIAL", "NOT_CAPTURED"]


class AuditDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class AuditModeCommand(AuditDTO):
    operation_id: str = Field(min_length=1, max_length=36)
    expected_version: int = Field(ge=0)
    mode: AuditMode


class AuditModeSnapshot(AuditDTO):
    mode: AuditMode = "OFF"
    version: int = 0


class AuditModeAdminSnapshot(AuditModeSnapshot):
    content_available: bool


class AuditRequestMetadata(AuditDTO):
    request_id: str
    user_id: int
    user_name: str | None = None
    session_id: str | None
    model_id: int
    model_name: str
    provider_name: str
    conversation_id: str | None = None
    request_kind: str | None = None
    session_origin: str | None = None
    parent_conversation_id: str | None = None
    association_status: Literal["ASSOCIATED", "UNASSOCIATED"]
    context_invalid: bool = False
    effective_mode: Literal["METADATA", "CONTENT"] | None
    started_at: datetime
    model_result: ModelResult | None
    response_result: ResponseResult | None
    usage_settlement: UsageSettlement | None
    content_status: ContentStatus
    input_units: int
    input_bytes: int
    output_bytes: int
    usage: dict | None = None
    model_error_code: str | None = None
    response_error_code: str | None = None
    last_write_at: datetime | None = None
    audit_status: Literal["NORMAL", "ABNORMAL", "NOT_APPLICABLE"] | None = None
    status_reasons: list[str] = Field(default_factory=list)
    status_pending: bool = False
    record_origin: Literal["MODEL", "EXTERNAL_SAFETY"] = "MODEL"
    model_entered: bool | None = None
    model_started_at: datetime | None = None
    source_id: str | None = None
    gateway_request_id: str | None = None
    content_safety_state: ContentSafetyState = "UNREPORTED"
    stage_results: StageResults = Field(default_factory=lambda: StageResults(input="UNREPORTED", output="UNREPORTED"))
    stage_versions: StageVersions = Field(default_factory=lambda: StageVersions(input=0, output=0))
    has_sensitive_hit: bool = False
    input_sensitive_hit: bool = False
    output_sensitive_hit: bool = False
    policy_version: int | None = None
    builtin_digest: str | None = None
    safety_observed_at: datetime | None = None
    details_status: SafetyDetailsStatus = "UNREPORTED"


class AuditProgress(AuditDTO):
    last_write_at: datetime | None = None
    pending_events: int | None = None
    coverage: Literal["OBSERVABLE_ESTIMATE"] = "OBSERVABLE_ESTIMATE"
    limitations: list[str] = Field(default_factory=lambda: ["buffers_and_evidence_can_both_be_lost"])


class AuditRequestPage(AuditDTO):
    items: list[AuditRequestMetadata]
    next_cursor: str | None = None
    progress: AuditProgress = Field(default_factory=AuditProgress)
