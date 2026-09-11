"""Deployment settings for the Open API surfaces."""

from pydantic import BaseModel, Field, field_validator


class OpenPlatformConf(BaseModel):
    enabled: bool = Field(default=False, description="Whether Open Platform extensions are deployed")


class OpenApiConf(BaseModel):
    credential_cache_ttl_seconds: int = Field(default=3, ge=0)
    service_account_idle_days: int = Field(default=90, ge=1)
    pat_enabled: bool = Field(default=False)
    pat_admin_ttl_days: int = Field(default=7, ge=1)
    management_ui_enabled: bool = Field(
        default=False,
        description=(
            "Whether the admin console shows the Open API surfaces (service accounts, "
            "personal tokens). Separate from pat_enabled, which governs the feature "
            "itself: a deployment can run service accounts with personal tokens off, "
            "and a release can ship the backend while the console stays hidden."
        ),
    )

    @field_validator("credential_cache_ttl_seconds")
    @classmethod
    def cap_credential_cache_ttl(cls, value: int) -> int:
        return min(value, 5)
