"""Tenant-scoped controls for personal Open API tokens."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT

DEFAULT_PAT_TTL_DAYS = 30


class OpenApiTenantSetting(SQLModelSerializable, table=True):
    __tablename__ = "open_api_tenant_setting"

    tenant_id: int = Field(sa_column=Column(Integer, primary_key=True, autoincrement=False))
    pat_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    pat_ttl_days: int = Field(
        default=DEFAULT_PAT_TTL_DAYS,
        sa_column=Column(Integer, nullable=False, server_default=text(str(DEFAULT_PAT_TTL_DAYS))),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )

