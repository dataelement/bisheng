"""Complete immutable request snapshots for Redis Stream and SQL projection."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, model_validator

from bisheng.dsh.domain.schemas.contracts import DshTokenUsage


class UsageEvent(DshTokenUsage):
    request_id: str = Field(min_length=1, max_length=36)
    tenant_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    # Historical events retain these fields for immutable audit replay.
    seat_id: str | None = Field(default=None, min_length=1, max_length=36)
    session_id: str = Field(min_length=1, max_length=36)
    grant_version: int | None = Field(default=None, gt=0)
    model_id: int = Field(gt=0)
    credit_rate: int = Field(default=100, ge=1, le=100000, strict=True)
    usage_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    billing_timezone: str = Field(min_length=1, max_length=64)
    policy_version: int = Field(gt=0)
    event_version: int = Field(gt=0)
    quota_epoch: int = Field(gt=0)
    status: Literal["RUNNING", "USAGE_UNKNOWN", "SUCCEEDED", "FAILED", "CANCELLED"]
    usage_source: Literal["PROVIDER", "RECONCILED"] | None = None
    started_at: datetime
    ended_at: datetime | None = None
    settled_at: datetime | None = None
    provider_request_id: str | None = Field(default=None, max_length=256)
    trace_id: str | None = Field(default=None, max_length=64)
    error_code: str | None = Field(default=None, max_length=64)
    latency_ms: int | None = Field(default=None, ge=0)
    operation_id: str | None = Field(default=None, max_length=36)
    operation_generation: int | None = Field(default=None, gt=0)
    payload_hash: str | None = Field(default=None, max_length=64)

    @property
    def billed_tokens(self) -> int | None:
        """Round each call up to one microcredit using integer arithmetic."""
        return None if self.total_tokens is None else (self.total_tokens * self.credit_rate + 99) // 100

    @model_validator(mode="after")
    def validate_state(self):
        if self.billed_tokens is not None and self.billed_tokens > 9_223_372_036_854_775_807:
            raise ValueError("Billed usage must fit the accounting range")
        reliable = self.total_tokens is not None
        if reliable != (self.status not in {"RUNNING", "USAGE_UNKNOWN"}):
            raise ValueError("Terminal events require reliable usage; unresolved events require NULL")
        if reliable != (self.usage_source is not None):
            raise ValueError("Reliable usage requires an evidence source")
        for key in ["started_at", "ended_at", "settled_at"]:
            value = getattr(self, key)
            if value is not None:
                if value.tzinfo is None:
                    value = value.replace(tzinfo=UTC)
                setattr(self, key, value.astimezone(UTC))
        return self
