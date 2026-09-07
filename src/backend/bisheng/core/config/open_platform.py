"""Deployment settings for the Open API surfaces."""

from pydantic import BaseModel, Field, field_validator


class OpenPlatformConf(BaseModel):
    enabled: bool = Field(default=False, description="Whether Open Platform extensions are deployed")


class OpenApiConf(BaseModel):
    credential_cache_ttl_seconds: int = Field(default=3, ge=0)
    service_account_idle_days: int = Field(default=90, ge=1)
    pat_enabled: bool = Field(default=False)
    pat_admin_ttl_days: int = Field(default=7, ge=1)

    @field_validator("credential_cache_ttl_seconds")
    @classmethod
    def cap_credential_cache_ttl(cls, value: int) -> int:
        return min(value, 5)
