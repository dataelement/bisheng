"""Complete immutable request snapshots for Redis Stream and SQL projection."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, model_validator

from bisheng.dsh.domain.schemas.contracts import DshTokenUsage
from bisheng.dsh.domain.schemas.pricing import PricingSnapshot, price_usage

INT64_MAX = 9_223_372_036_854_775_807


class UsageEvent(DshTokenUsage):
    request_id: str = Field(min_length=1, max_length=36)
    tenant_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    # Historical events retain these fields for immutable audit replay.
    seat_id: str | None = Field(default=None, min_length=1, max_length=36)
    session_id: str = Field(min_length=1, max_length=36)
    grant_version: int | None = Field(default=None, gt=0)
    model_id: int = Field(gt=0)
    # Legacy multiplier: only events without a price snapshot (pre-F015) are billed by it.
    credit_rate: int = Field(default=100, ge=1, le=100000, strict=True)
    # F015: prices frozen when the call started; None only on pre-F015 events.
    pricing: PricingSnapshot | None = None
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
        """Microcredits charged for this call, rounded up with integer arithmetic."""
        if self.total_tokens is None:
            return None
        if self.pricing is None:
            # Pre-F015 events keep their original rule so recovery can still rebuild their month.
            return (self.total_tokens * self.credit_rate + 99) // 100
        return price_usage(self, self.pricing).billed

    @property
    def cost_micro(self) -> int | None:
        """Spend in billing-currency micro-units; None without a snapshot or usage."""
        if self.pricing is None or self.total_tokens is None:
            return None
        return price_usage(self, self.pricing).cost_micro

    @property
    def currency(self) -> str | None:
        return None if self.pricing is None else self.pricing.currency

    @model_validator(mode="after")
    def validate_state(self):
        if self.billed_tokens is not None and self.billed_tokens > INT64_MAX:
            raise ValueError("Billed usage must fit the accounting range")
        if self.cost_micro is not None and self.cost_micro > INT64_MAX:
            raise ValueError("Call cost must fit the accounting range")
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
