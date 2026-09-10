"""Optional DSH settings; construction never loads application secrets or IO."""

from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DshSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    enabled: bool = Field(default=False, description="Enable DSH Desktop model access; disabled by default.")
    client_id: Literal["dsh-desktop"] = Field(
        default="dsh-desktop", description="Desktop OAuth client identifier fixed by the DSH contract."
    )
    contract_version: Literal["0.4.0"] = Field(
        default="0.4.0", description="DSH wire contract version shared with the gateway and Desktop."
    )
    installation_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]{1,64}$",
        description="Stable platform installation identifier used to scope DSH trust and quota state.",
    )
    platform_public_url: str | None = Field(
        default=None, description="Public HTTP(S) origin of Bisheng used by the Desktop authorization flow; no path."
    )
    gateway_internal_url: str | None = Field(
        default=None,
        description="Internal HTTP(S) origin of the gateway used for authenticated service calls; no path.",
    )
    quota_approval_object: str | None = Field(
        default=None,
        description="Immutable object reference containing the approval required to activate quota storage.",
    )
    quota_approval_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
        description="Lowercase SHA-256 digest of the quota activation approval object; required with its reference.",
    )
    quota_evidence_bucket: str = Field(
        default="dsh-evidence",
        min_length=3,
        max_length=63,
        description="Object-storage bucket containing immutable quota approval and reconciliation evidence.",
    )
    billing_timezone: str = Field(
        default="Asia/Shanghai", description="IANA timezone used to calculate monthly quota accounting boundaries."
    )
    introspection_timeout_seconds: float = Field(
        default=2.0, gt=0, le=30, description="Maximum duration in seconds of a gateway token introspection request."
    )
    projection_target_seconds: int = Field(
        default=5, gt=0, description="Target latency in seconds for projecting usage events from Redis into SQL."
    )
    backlog_stop_seconds: int = Field(
        default=30, gt=0, description="Usage projection backlog age in seconds at which new model requests must stop."
    )

    quota_memory_budget_bytes: int = Field(
        default=536870912,
        ge=1048576,
        description="Finite memory budget in bytes for the isolated authoritative quota Redis instance.",
    )
    quota_memory_headroom_bytes: int = Field(
        default=67108864,
        ge=1048576,
        description="Memory in bytes reserved below the quota Redis budget to finish in-flight settlements.",
    )
    quota_backlog_high_watermark: int = Field(
        default=10000, ge=1, description="Maximum pending usage-event backlog before new model requests must stop."
    )
    quota_retention_seconds: int = Field(
        default=2592000,
        ge=86400,
        description="Minimum age in seconds before projected quota events can be removed during maintenance.",
    )
    quota_projection_max_batches: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum usage-event batches processed in one projection worker invocation.",
    )
    quota_projection_max_seconds: float = Field(
        default=1.0,
        gt=0,
        le=10,
        description="Maximum duration in seconds spent processing batches in one projection invocation.",
    )

    @field_validator("platform_public_url", "gateway_internal_url")
    @classmethod
    def validate_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("DSH endpoints require a credential-free HTTP(S) origin without a path")
        try:
            _ = parsed.port
        except ValueError:
            raise ValueError("Invalid DSH origin port") from None
        return value.rstrip("/")

    @field_validator("billing_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown billing timezone") from None
        return value

    @model_validator(mode="after")
    def validate_enabled_trust(self):
        if bool(self.quota_approval_object) != bool(self.quota_approval_sha256):
            raise ValueError("Quota approval requires both immutable object reference and SHA256")
        if self.quota_memory_headroom_bytes >= self.quota_memory_budget_bytes:
            raise ValueError("Quota capacity requires positive settlement headroom below its finite memory budget")
        if not self.enabled:
            return self
        names = (
            "installation_id",
            "platform_public_url",
            "gateway_internal_url",
        )
        if any(not getattr(self, name) for name in names):
            raise ValueError("Enabled DSH requires instance and endpoint addresses")
        if self.backlog_stop_seconds <= self.projection_target_seconds:
            raise ValueError("Backlog threshold must exceed the projection target")
        return self
