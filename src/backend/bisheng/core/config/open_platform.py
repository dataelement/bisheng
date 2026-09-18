"""Deployment settings for the Open API surfaces."""

from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


class OpenPlatformConf(BaseModel):
    enabled: bool = Field(default=False, description="Whether Open Platform extensions are deployed")


class OpenApiConf(BaseModel):
    credential_cache_ttl_seconds: int = Field(default=3, ge=0)
    service_account_idle_days: int = Field(default=90, ge=1)
    pat_enabled: bool = Field(
        default=True,
        description=(
            "Whether this deployment offers personal access tokens at all. This is "
            "only the deployment half: a token can be issued once a tenant admin "
            "also turns them on for the tenant, which is off until someone does. "
            "Set false to withdraw the feature from a deployment outright."
        ),
    )
    pat_admin_ttl_days: int = Field(default=7, ge=1)
    management_ui_enabled: bool = Field(
        default=True,
        description=(
            "Whether the admin console shows the Open API surfaces (service accounts, "
            "personal tokens). Separate from pat_enabled, which governs the feature "
            "itself: a deployment can run service accounts with personal tokens off. "
            "Both defaulted to false while F053 was still being built, so that COFCO "
            "could test the 3.0 upgrade without an unfinished surface in the console."
        ),
    )

    public_base_url: str = Field(
        default="",
        description=(
            "Browser-facing address of this platform, scheme://host[:port][/prefix], "
            "baked into downloaded skill packs and install prompts. Leave empty to "
            "derive it from the reverse proxy's X-Forwarded-Proto / X-Forwarded-Host "
            "headers; set it when the backend sits behind the commercial gateway, a "
            "path prefix, or any proxy that does not forward those headers."
        ),
    )

    @field_validator("credential_cache_ttl_seconds")
    @classmethod
    def cap_credential_cache_ttl(cls, value: int) -> int:
        return min(value, 5)

    @field_validator("public_base_url")
    @classmethod
    def normalise_public_base_url(cls, value: str) -> str:
        text = (value or "").strip().rstrip("/")
        if not text:
            return ""
        parts = urlsplit(text)
        if parts.scheme not in {"http", "https"} or not parts.netloc or parts.query or parts.fragment:
            raise ValueError(
                "open_api.public_base_url must be an absolute http(s) URL such as "
                "https://kb.example.com or https://portal.example.com/bisheng"
            )
        return text


class OpenMcpConf(BaseModel):
    """Inbound MCP transport and file-adaptation safety limits."""

    max_inline_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    file_url_allowed_hosts: list[str] = Field(default_factory=list)
    transport_allowed_hosts: list[str] = Field(
        default_factory=lambda: [
            "127.0.0.1",
            "127.0.0.1:*",
            "localhost",
            "localhost:*",
            "[::1]",
            "[::1]:*",
        ]
    )
    transport_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:*",
            "http://127.0.0.1",
            "http://localhost:*",
            "http://localhost",
            "http://[::1]:*",
            "http://[::1]",
        ]
    )
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    read_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    max_redirects: int = Field(default=3, ge=0, le=10)

    @field_validator("file_url_allowed_hosts")
    @classmethod
    def normalize_hosts(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            host = value.strip().lower().rstrip(".")
            if not host or "://" in host or "/" in host or "@" in host:
                raise ValueError("open_mcp allowed hosts must contain host names only")
            if host not in normalized:
                normalized.append(host)
        return normalized

    @field_validator("transport_allowed_hosts")
    @classmethod
    def validate_transport_hosts(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if any("/" in value or "://" in value or "@" in value for value in normalized):
            raise ValueError("open_mcp transport_allowed_hosts must contain Host header values")
        return list(dict.fromkeys(normalized))

    @field_validator("transport_allowed_origins")
    @classmethod
    def validate_transport_origins(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().rstrip("/") for value in values if value.strip()]
        for value in normalized:
            candidate = value[:-2] if value.endswith(":*") else value
            parts = urlsplit(candidate)
            if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path or parts.query or parts.fragment:
                raise ValueError("open_mcp transport_allowed_origins must contain HTTP origins")
        return list(dict.fromkeys(normalized))

    @property
    def max_base64_characters(self) -> int:
        return 4 * ((self.max_inline_upload_bytes + 2) // 3)

    @property
    def max_request_body_bytes(self) -> int:
        return self.max_base64_characters + 1024 * 1024
