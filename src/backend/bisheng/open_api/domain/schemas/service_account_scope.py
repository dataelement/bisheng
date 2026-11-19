"""Scope selection cannot mutate an existing service account's tenant."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class ServiceAccountScopeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: StrictInt = Field(gt=0)


class ServiceAccountScopeResult(BaseModel):
    scope_tenant_id: int | None
    expires_at: str | None


class ServiceAccountOwnerCandidate(BaseModel):
    user_id: int
    user_name: str
    tenant_id: int
