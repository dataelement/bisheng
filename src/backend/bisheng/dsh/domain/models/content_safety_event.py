"""Tenant-isolated content-safety facts without model content or credentials."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, Index, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType, PreciseDateTime


class DshContentSafetyEvent(SQLModelSerializable, table=True):
    __tablename__ = "dsh_content_safety_event"
    __table_args__ = (
        UniqueConstraint("source_id", "event_id", name="uq_dcse_source_event"),
        UniqueConstraint("source_id", "gateway_request_id", "event_version", name="uq_dcse_request_version"),
        Index("ix_dcse_audit", "tenant_id", "audit_request_id", "occurred_at", "id"),
        Index("ix_dcse_unassociated", "tenant_id", "association_status", "request_started_at", "id"),
        Index("ix_dcse_request", "tenant_id", "source_id", "gateway_request_id", "event_version", "event_id"),
        Index("ix_dcse_cleanup", "tenant_id", "received_at", "id"),
        CheckConstraint("schema_version = 1", name="ck_dcse_schema"),
        CheckConstraint("event_version > 0", name="ck_dcse_version"),
        CheckConstraint("hit_count >= 0", name="ck_dcse_hits"),
        CheckConstraint("protocol IN ('CHAT','RESPONSES')", name="ck_dcse_protocol"),
        CheckConstraint("event_kind IN ('DECISION','FINAL','DRAIN')", name="ck_dcse_kind"),
    )
    id: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(String(36), primary_key=True))
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=text("CURRENT_TIMESTAMP")
        ),
    )
    source_id: str = Field(sa_column=Column(String(64), nullable=False))
    event_id: str = Field(sa_column=Column(String(36), nullable=False))
    gateway_request_id: str = Field(sa_column=Column(String(36), nullable=False))
    backend_request_id: str | None = Field(default=None, sa_column=Column(String(36)))
    audit_request_id: str | None = Field(default=None, sa_column=Column(String(36)))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    model_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    session_id: str | None = Field(default=None, sa_column=Column(String(128)))
    schema_version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    event_version: int = Field(sa_column=Column(BigInteger, nullable=False))
    event_kind: str = Field(sa_column=Column(String(16), nullable=False))
    protocol: str = Field(sa_column=Column(String(16), nullable=False))
    request_started_at: datetime = Field(sa_column=Column(PreciseDateTime(), nullable=False))
    occurred_at: datetime = Field(sa_column=Column(PreciseDateTime(), nullable=False))
    received_at: datetime = Field(sa_column=Column(PreciseDateTime(), nullable=False))
    payload_hash: str = Field(sa_column=Column(String(64), nullable=False))
    stage_results: dict = Field(sa_column=Column(JsonType, nullable=False))
    stage_versions: dict = Field(sa_column=Column(JsonType, nullable=False))
    policy_version: int = Field(sa_column=Column(BigInteger, nullable=False))
    builtin_digest: str = Field(sa_column=Column(String(64), nullable=False))
    hit_count: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    hit_count_truncated: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=text("0"))
    )
    rule_refs: list[str] = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))
    matched_words: dict | None = Field(default=None, sa_column=Column(JsonType, nullable=True))
    forwarded: bool = Field(sa_column=Column(Boolean, nullable=False))
    drain_status: str = Field(sa_column=Column(String(32), nullable=False))
    association_status: str = Field(default="UNASSOCIATED", sa_column=Column(String(32), nullable=False))
    conversation: dict | None = Field(default=None, sa_column=Column(JsonType))
