from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType


class ApprovalNotificationEventType:
    FILE_PUBLISH_SUBMITTED = "file_publish_submitted"


class ApprovalNotificationOutboxStatus:
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class ApprovalNotificationOutbox(SQLModelSerializable, table=True):
    __tablename__ = "approval_notification_outbox"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "instance_id",
            "event_type",
            name="uk_approval_notification_outbox_event",
        ),
        Index(
            "idx_approval_notification_outbox_dispatch",
            "status",
            "retry_count",
            "update_time",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False),
    )
    instance_id: int = Field(sa_column=Column(Integer, nullable=False))
    event_type: str = Field(sa_column=Column(String(64), nullable=False))
    status: str = Field(
        default=ApprovalNotificationOutboxStatus.PENDING,
        sa_column=Column(String(32), nullable=False),
    )
    retry_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    max_retries: int = Field(
        default=3,
        sa_column=Column(Integer, nullable=False, server_default=text("3")),
    )
    payload_snapshot: dict = Field(
        default_factory=dict,
        sa_column=Column(JsonType, nullable=False),
    )
    error_summary: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )
