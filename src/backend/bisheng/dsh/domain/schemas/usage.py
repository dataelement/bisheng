"""Complete immutable request snapshots for Redis Stream and SQL projection."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bisheng.dsh.domain.schemas.contracts import DshTokenUsage
from bisheng.dsh.domain.schemas.pricing import PricingSnapshot, price_usage

INT64_MAX = 9_223_372_036_854_775_807


class ToolPricingSnapshot(BaseModel):
    """Frozen tool billing parameters recorded at execution time."""

    model_config = ConfigDict(extra="forbid")

    pricing_mode: Literal["MONEY", "CREDITS"]
    currency: Literal["CNY", "USD"] | None = None
    price_micro: int = Field(ge=0)
    call_count: int = Field(ge=1, le=1_000_000)
    credit_value_micro: int = Field(ge=1)
    usd_cny_rate_micro: int | None = Field(default=None, ge=1)


class ToolUsageEvent(BaseModel):
    """Atomic tool call billing event persisted via Redis Stream to dsh_tool_call."""

    model_config = ConfigDict(extra="forbid")

    event_kind: Literal["tool"] = "tool"
    request_id: str = Field(min_length=1, max_length=36)
    tenant_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    usage_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    billing_timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    quota_epoch: int = Field(default=1, gt=0)
    event_version: int = Field(default=1, gt=0)
    tool_group_id: int = Field(ge=0)
    tool_group_name: str | None = Field(default=None, max_length=256)
    tool_id: int = Field(gt=0)
    tool_key: str = Field(min_length=1, max_length=128)
    engine: str | None = Field(default=None, max_length=64)
    pricing_snapshot: ToolPricingSnapshot | dict | None = None
    billed_tokens: int = Field(ge=0, le=INT64_MAX)
    cost_micro: int | None = Field(default=None, ge=0, le=INT64_MAX)
    currency: Literal["CNY", "USD"] | None = None
    result: Literal["success", "failed", "timeout", "cancelled"] = "success"
    status: Literal["SUCCEEDED"] = "SUCCEEDED"
    source_type: str | None = Field(default=None, max_length=32)
    source_id: str | None = Field(default=None, max_length=64)
    started_at: datetime
    ended_at: datetime | None = None

    @model_validator(mode="after")
    def normalize_timestamps(self):
        for key in ("started_at", "ended_at"):
            value = getattr(self, key)
            if value is not None:
                if value.tzinfo is None:
                    value = value.replace(tzinfo=UTC)
                setattr(self, key, value.astimezone(UTC))
        return self


class UsageEvent(DshTokenUsage):
    request_id: str = Field(min_length=1, max_length=36)
    tenant_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    # Historical events retain these fields for immutable audit replay.
    seat_id: str | None = Field(default=None, min_length=1, max_length=36)
    session_id: str = Field(min_length=1, max_length=36)
    grant_version: int | None = Field(default=None, gt=0)
    model_id: int = Field(gt=0)
    # Legacy multiplier: only events without a price snapshot (pre-F016) are billed by it.
    credit_rate: int = Field(default=100, ge=1, le=100000, strict=True)
    # F016: prices frozen when the call started; None only on pre-F016 events.
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
    source_type: str | None = Field(default=None, max_length=32)
    source_id: str | None = Field(default=None, max_length=64)
    payload_hash: str | None = Field(default=None, max_length=64)

    @property
    def billed_tokens(self) -> int | None:
        """Microcredits charged for this call, rounded up with integer arithmetic."""
        if self.total_tokens is None:
            return None
        if self.pricing is None:
            # Pre-F016 events keep their original rule so recovery can still rebuild their month.
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


def parse_usage_event_json(raw: str, *, event_kind: str | None = None) -> "UsageEvent | ToolUsageEvent":
    """Deserialize either a model UsageEvent or a ToolUsageEvent from JSON."""
    if event_kind == "tool":
        return ToolUsageEvent.model_validate_json(raw)
    if event_kind in (None, "") and '"event_kind":"tool"' in raw.replace(" ", ""):
        return ToolUsageEvent.model_validate_json(raw)
    return UsageEvent.model_validate_json(raw)


def parse_stream_usage_event(fields: dict) -> "UsageEvent | ToolUsageEvent":
    """Parse one Redis Stream entry using optional event_kind discriminator."""
    return parse_usage_event_json(fields["event"], event_kind=fields.get("event_kind"))
