"""Service-account DTOs (F049 design §4.2, list columns per AC-42 / AC-23)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from bisheng.common.schemas.api import PageData

ServiceAccountStatus = Literal["enabled", "disabled", "deleted"]


class ServiceAccountCreate(BaseModel):
    """``POST /api/v1/service-accounts``. Tenant = the admin's current tenant, never chosen (AC-23)."""

    name: str = Field(..., min_length=1, max_length=64, description="Becomes user.user_name")
    description: str | None = Field(default=None, max_length=512)
    resource_owner_user_id: int = Field(..., description="Enabled natural person of this tenant (26021 otherwise)")

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class ServiceAccountUpdate(BaseModel):
    """``PATCH /api/v1/service-accounts/{id}`` - name / description / resource owner (AC-27: not retroactive)."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    resource_owner_user_id: int | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class ServiceAccountOwner(BaseModel):
    """Resource owner as shown in list / detail; ``disabled`` drives the AC-28 / AC-42 highlight."""

    user_id: int
    user_name: str | None = None
    disabled: bool = Field(default=False, description="Owner user is disabled or deleted (account keeps working)")


class ServiceAccountItem(BaseModel):
    """List row: name / status / valid key count / owner (+ owner_disabled) / last call / creator / created."""

    id: int = Field(description="= user.user_id of the service-account principal")
    name: str
    description: str | None = None
    status: ServiceAccountStatus
    disabled_at: datetime | None = None
    deleted_at: datetime | None = None
    active_key_count: int = 0
    resource_owner: ServiceAccountOwner | None = None
    owner_disabled: bool = False
    last_used_at: datetime | None = Field(default=None, description="max(last_used_at) over the account's keys")
    idle: bool = Field(default=False, description="No call within settings.open_api.service_account_idle_days")
    created_by: int | None = None
    creator_name: str | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None


class ServiceAccountDetail(ServiceAccountItem):
    tenant_id: int


class ServiceAccountPage(PageData[ServiceAccountItem]):
    """``PageData`` + meta: the idle threshold the UI compares ``last_used_at`` against (AC-42)."""

    idle_days: int
