"""Portable, tenant-owned marketplace records; artifact bytes live in object storage."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, UniqueConstraint, false
from sqlmodel import Field, SQLModel

from bisheng.core.database.dialect_helpers import JsonType


def now():
    return datetime.now(UTC).replace(tzinfo=None)


class MarketPlugin(SQLModel, table=True):
    __tablename__ = "dsh_market_plugin"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_dsh_market_plugin_tenant_name"),)
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True, max_length=32)
    tenant_id: int = Field(index=True)
    name: str = Field(max_length=214)
    display_name: str = Field(max_length=128)
    description: str = Field(max_length=2000)
    current_version_id: str | None = Field(default=None, max_length=32)
    deleted: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=false()))
    disabled: bool = False
    revision: int = 1
    updated_at: datetime = Field(default_factory=now)


class MarketVersion(SQLModel, table=True):
    __tablename__ = "dsh_market_version"
    __table_args__ = (UniqueConstraint("tenant_id", "plugin_id", "version", name="uq_dsh_market_version_identity"),)
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True, max_length=32)
    tenant_id: int = Field(index=True)
    plugin_id: str = Field(index=True, max_length=32)
    version: str = Field(max_length=64)
    digest: str = Field(max_length=64)
    size: int
    manifest: dict = Field(sa_column=Column(JsonType, nullable=False))
    # Preserve the existing column while tracking publication history for installed clients.
    published_once: bool = Field(default=False, sa_column=Column("reviewed", Boolean, nullable=False, default=False))
    created_at: datetime = Field(default_factory=now)


class MarketImport(SQLModel, table=True):
    __tablename__ = "dsh_market_import"
    __table_args__ = (UniqueConstraint("tenant_id", "digest", name="uq_dsh_market_import_digest"),)
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True, max_length=32)
    tenant_id: int = Field(index=True)
    actor_id: int
    digest: str = Field(max_length=64)
    status: str = Field(default="validating", max_length=16)
    error: str = Field(default="", max_length=512)
    version_id: str | None = Field(default=None, max_length=32)
    created_at: datetime = Field(default_factory=now)


class MarketAudit(SQLModel, table=True):
    __tablename__ = "dsh_market_audit"
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True, max_length=32)
    tenant_id: int = Field(index=True)
    actor_id: int
    plugin_id: str = Field(index=True, max_length=32)
    version_id: str | None = Field(default=None, max_length=32)
    action: str = Field(max_length=32)
    revision: int
    before: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    after: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    result: str = Field(default="succeeded", max_length=16)
    created_at: datetime = Field(default_factory=now)


class MarketDevice(SQLModel, table=True):
    __tablename__ = "dsh_market_device"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "device_id", name="uq_dsh_market_device_identity"),)
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True, max_length=32)
    tenant_id: int = Field(index=True)
    user_id: int
    device_id: str = Field(max_length=64)
    plugins: list = Field(sa_column=Column(JsonType, nullable=False))
    synced_at: datetime = Field(default_factory=now)
