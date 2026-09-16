"""Deployment settings for the Open API surfaces."""

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

    @field_validator("credential_cache_ttl_seconds")
    @classmethod
    def cap_credential_cache_ttl(cls, value: int) -> int:
        return min(value, 5)
