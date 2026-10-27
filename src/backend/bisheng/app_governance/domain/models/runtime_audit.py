"""Short lived private read conditions and asynchronous export ownership."""

from datetime import datetime

from sqlalchemy import Column, Integer, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType
from bisheng.utils import generate_uuid


class RuntimeAuditQuerySnapshot(SQLModelSerializable, table=True):
    __tablename__ = "runtime_audit_query_snapshot"
    id: str = Field(default_factory=generate_uuid, primary_key=True, max_length=36)
    tenant_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    creator_user_id: int = Field(index=True)
    scope_tenant_id: int | None = None
    kind: str = Field(max_length=16)
    normalized_filter: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    filter_digest: str = Field(max_length=64)
    watermark: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime


class RuntimeAuditExport(SQLModelSerializable, table=True):
    __tablename__ = "runtime_audit_export"
    __table_args__ = (UniqueConstraint("creator_user_id", "request_id", name="uq_runtime_audit_export_request"),)
    id: str = Field(default_factory=generate_uuid, primary_key=True, max_length=36)
    tenant_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    creator_user_id: int = Field(index=True)
    scope_tenant_id: int | None = None
    kind: str = Field(max_length=16)
    snapshot_id: str = Field(max_length=36)
    request_id: str = Field(max_length=128)
    normalized_filter: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    watermark: int = 0
    status: str = Field(default="pending", max_length=16, index=True)
    attempt: int = 0
    lease_holder: str = Field(default="", max_length=64)
    epoch: int = 0
    lease_until: datetime | None = None
    selection_started_at: datetime | None = None
    processed_rows: int = 0
    final_count: int | None = None
    manifest_object_key: str | None = Field(default=None, max_length=512)
    manifest_digest: str | None = Field(default=None, max_length=64)
    ready_at: datetime | None = None
    download_expires_at: datetime | None = None
    gc_completed_at: datetime | None = None
    safe_failure: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow)
