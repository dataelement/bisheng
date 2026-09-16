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
    model_catalog_ttl_seconds: int = Field(
        default=30,
        ge=1,
        description=(
            "How long the model protocol face caches a tenant's callable model "
            "catalog. Capped at 60s because that is the outward promise for a "
            "model taken offline in model management (F051 AC-14); the same 60s "
            "bound already governs the LLM row cache underneath."
        ),
    )
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

    @field_validator("model_catalog_ttl_seconds")
    @classmethod
    def cap_model_catalog_ttl(cls, value: int) -> int:
        return min(value, 60)

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
