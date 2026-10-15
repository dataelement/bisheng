"""Audit management DTOs; body data never belongs to metadata responses."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class AuditRequestMetadata(AuditDTO):
    request_id: str
    user_id: int
    session_id: str
    model_id: int
    model_name: str
    provider_name: str
    conversation_id: str | None = None
    request_kind: str | None = None
    association_status: Literal["ASSOCIATED", "UNASSOCIATED"]
    context_invalid: bool = False
    effective_mode: Literal["METADATA", "CONTENT"]
    started_at: datetime
    model_result: ModelResult
    response_result: ResponseResult
    usage_settlement: UsageSettlement
    content_status: ContentStatus
    input_units: int
    input_bytes: int
    output_bytes: int
    usage: dict | None = None
    last_write_at: datetime | None = None


class AuditProgress(AuditDTO):
    last_write_at: datetime | None = None
    pending_events: int | None = None
    coverage: Literal["OBSERVABLE_ESTIMATE"] = "OBSERVABLE_ESTIMATE"
    limitations: list[str] = Field(default_factory=lambda: ["buffers_and_evidence_can_both_be_lost"])


class AuditRequestPage(AuditDTO):
    items: list[AuditRequestMetadata]
    next_cursor: str | None = None
    progress: AuditProgress = Field(default_factory=AuditProgress)
