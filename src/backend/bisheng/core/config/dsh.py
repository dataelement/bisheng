"""Optional DSH settings; construction never loads application secrets or IO."""

from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator


def normalize_dsh_origin(value: str) -> str:
    """Use the browser's canonical HTTP authority for every DSH consumer."""
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise ValueError("DSH origin requires an unambiguous HTTP(S) address")
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
    if parsed.port == 0:
        raise ValueError("DSH origin requires a port between 1 and 65535")
    # URL consumers serialize DNS names, default ports and IPv6 literals this way.
    # Normalize once so OAuth Origin checks and MCP use the same representation.
    return str(AnyHttpUrl(value)).rstrip("/")


class DshSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    access_ttl_seconds: int = Field(
        default=300, ge=60, le=600, description="Lifetime in seconds of a native DSH access token."
    )
    session_ttl_seconds: int = Field(
        default=2592000, ge=600, le=2592000, description="Absolute lifetime in seconds of a native desktop session."
    )

    enabled: bool = Field(
        default=False,
        description="Expose the DSH management module; disabled by default. Business access is enabled separately in its management page.",
    )
    client_id: Literal["dsh-desktop"] = Field(
        default="dsh-desktop", description="Desktop OAuth client identifier fixed by the DSH contract."
    )
    contract_version: Literal["0.5.0"] = Field(
        default="0.5.0", description="DSH wire contract version shared with Desktop."
    )
    platform_public_url: str | None = Field(
        default=None,
        description="Single public HTTP(S) origin shared by Desktop login, Chat and Work tools; include the public port and omit paths.",
    )
    web_session_cookie_name: str = Field(
        default="access_token_cookie",
        pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$",
        description="Public ingress cookie name used by the isolated Desktop browser session.",
    )
    gateway_internal_url: str | None = Field(
        default=None,
        description="Deprecated compatibility field; native DSH never connects to this address.",
    )
    billing_timezone: str = Field(
        default="Asia/Shanghai", description="IANA timezone used to calculate monthly quota accounting boundaries."
    )
    introspection_timeout_seconds: float = Field(
        default=2.0,
        gt=0,
        le=30,
        description="Deprecated compatibility field; native session validation uses local SQL.",
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

    # Operational bounds, not a latency/coverage SLA or tenant-mode cache.
    audit_chunk_bytes: int = Field(
        default=16384, ge=1024, le=65536, description="Maximum encoded body fragment size in bytes."
    )
    audit_request_budget_bytes: int = Field(
        default=16777216, ge=65536, description="Maximum body bytes captured per request; exhaustion marks incomplete."
    )
    audit_queue_budget_bytes: int = Field(
        default=67108864,
        ge=65536,
        description="Per-process body budget across active, queued and writing requests, including fragment overhead; control events have a separate bounded queue.",
    )
    audit_queue_max_events: int = Field(
        default=4096,
        ge=1,
        description="Maximum buffered control events and, independently, active/queued/writing body requests; stream fragments do not consume event slots.",
    )
    audit_mode_read_timeout_seconds: float = Field(
        default=0.1, gt=0, le=5, description="Bounded authoritative tenant-mode read; failure falls back to OFF."
    )
    audit_store_timeout_seconds: float = Field(
        default=5.0, gt=0, le=60, description="Timeout for each background audit storage operation."
    )
    audit_write_attempts: int = Field(default=3, ge=1, le=5, description="Finite background storage retry count.")
    audit_activity_interval_seconds: float = Field(
        default=10.0, gt=0, description="Background active-request lease refresh interval."
    )
    audit_observation_window_seconds: float = Field(
        default=300.0, gt=0, description="Adjustable audit observation window, not a model timeout."
    )
    audit_state_scan_interval_seconds: float = Field(
        default=60.0, ge=10, le=3600, description="Beat interval for bounded historical audit convergence."
    )
    audit_shutdown_seconds: float = Field(
        default=5.0, gt=0, le=30, description="Maximum graceful audit drain duration."
    )
    audit_active_key_id: str | None = Field(
        default=None, max_length=64, description="Active external audit encryption key reference; no key material."
    )

    @field_validator("platform_public_url", "gateway_internal_url")
    @classmethod
    def validate_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_dsh_origin(value)

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
        if self.quota_memory_headroom_bytes >= self.quota_memory_budget_bytes:
            raise ValueError("Quota capacity requires positive settlement headroom below its finite memory budget")
        if not self.enabled:
            return self
        names = ("platform_public_url",)
        if any(not getattr(self, name) for name in names):
            raise ValueError("Enabled DSH requires endpoint addresses")
        if self.backlog_stop_seconds <= self.projection_target_seconds:
            raise ValueError("Backlog threshold must exceed the projection target")
        return self
