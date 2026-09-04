"""Service-account management schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ServiceAccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    resource_owner_user_id: int = Field(gt=0)


class ServiceAccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    resource_owner_user_id: int | None = Field(default=None, gt=0)


class ServiceAccountOwner(BaseModel):
    user_id: int
    user_name: str | None
    disabled: bool


class ServiceAccountItem(BaseModel):
    id: int
    tenant_id: int
    name: str
    description: str | None
    status: str
    resource_owner: ServiceAccountOwner
    active_key_count: int = 0
    last_used_at: datetime | None = None
    idle: bool = False
    created_by: int | None
    create_time: datetime | None
    update_time: datetime | None


class ServiceAccountDetail(ServiceAccountItem):
    disabled_at: datetime | None


class ServiceAccountPage(BaseModel):
    data: list[ServiceAccountItem]
    total: int
    idle_days: int
