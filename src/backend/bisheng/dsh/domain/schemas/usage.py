"""Complete immutable request snapshots for Redis Stream and SQL projection."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, model_validator

from bisheng.dsh.domain.schemas.contracts import DshTokenUsage


class UsageEvent(DshTokenUsage):
    request_id: str = Field(min_length=1, max_length=36)
    tenant_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    seat_id: str = Field(min_length=1, max_length=36)
    session_id: str = Field(min_length=1, max_length=36)
    grant_version: int = Field(gt=0)
    model_id: int = Field(gt=0)
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

    @model_validator(mode="after")
    def validate_state(self):
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
