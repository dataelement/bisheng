"""Independent service-account authorization subjects."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class ServiceAccount(SQLModelSerializable, table=True):
    """A non-login principal that is deliberately unrelated to ``user`` rows."""

    __tablename__ = "service_account"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uk_service_account_tenant_name"),
        Index("idx_service_account_tenant_status", "tenant_id", "deleted_at", "disabled_at"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, index=True, comment="Tenant ID"),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(String(512), nullable=True))
    resource_owner_user_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True, comment="Natural-person business owner"),
    )
    created_by: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    disabled_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    deleted_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )

    @property
    def is_enabled(self) -> bool:
        return self.disabled_at is None and self.deleted_at is None
