from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType


class DepartmentTransferCleanupEventStatus:
    PREPARING = "preparing"
    PENDING = "pending"
    PROCESSING = "processing"
    FAILED = "failed"
    OVERDUE = "overdue"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"

    TERMINAL = frozenset({SUCCEEDED, CANCELLED})
    RETRYABLE = frozenset({PENDING, FAILED, OVERDUE})


class DepartmentTransferCleanupItemStatus:
    PENDING = "pending"
    PROTECTED = "protected"
    REVOKED = "revoked"
    SKIPPED = "skipped"
    FAILED = "failed"

    TERMINAL = frozenset({PROTECTED, REVOKED, SKIPPED})
    PROCESSABLE = frozenset({PENDING, FAILED})


class DepartmentTransferCleanupItemType:
    REBAC_TUPLE = "rebac_tuple"
    SPACE_MEMBERSHIP = "space_membership"
    DEPARTMENT_FILE_GRANT = "department_file_grant"


class DepartmentTransferPermissionCleanupEvent(SQLModelSerializable, table=True):
    __tablename__ = "department_transfer_permission_cleanup_event"
    __table_args__ = (
        UniqueConstraint("event_key", name="uk_dtpc_event_key"),
        Index("idx_dtpc_status_retry", "status", "next_retry_at"),
        Index("idx_dtpc_user_changed", "user_id", "changed_at"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1")),
    )
    event_key: str = Field(sa_column=Column(String(128), nullable=False))
    user_id: int = Field(sa_column=Column(Integer, nullable=False))
    old_department_id: int = Field(sa_column=Column(Integer, nullable=False))
    new_department_id: int = Field(sa_column=Column(Integer, nullable=False))
    trigger_source: str = Field(sa_column=Column(String(32), nullable=False))
    status: str = Field(
        default=DepartmentTransferCleanupEventStatus.PREPARING,
        sa_column=Column(String(24), nullable=False, server_default=text("'preparing'")),
    )
    requested_at: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    changed_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    deadline_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    completed_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    overdue_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    next_retry_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    retry_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    snapshot_complete: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    total_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    revoked_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    protected_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    skipped_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    failed_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    last_error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class DepartmentTransferPermissionCleanupItem(SQLModelSerializable, table=True):
    __tablename__ = "department_transfer_permission_cleanup_item"
    __table_args__ = (
        UniqueConstraint("event_id", "item_key", name="uk_dtpc_item_event_key"),
        Index("idx_dtpc_item_user_status", "user_id", "status"),
        Index("idx_dtpc_item_event_status", "event_id", "status"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1")),
    )
    event_id: int = Field(sa_column=Column(Integer, nullable=False))
    item_key: str = Field(sa_column=Column(String(255), nullable=False))
    item_type: str = Field(sa_column=Column(String(32), nullable=False))
    user_id: int = Field(sa_column=Column(Integer, nullable=False))
    resource_type: str = Field(sa_column=Column(String(32), nullable=False))
    resource_id: str = Field(sa_column=Column(String(64), nullable=False))
    root_space_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    relation: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    source_ref: str | None = Field(default=None, sa_column=Column(String(128), nullable=True))
    snapshot: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    status: str = Field(
        default=DepartmentTransferCleanupItemStatus.PENDING,
        sa_column=Column(String(24), nullable=False, server_default=text("'pending'")),
    )
    protected_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    protected_source: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    processed_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    retry_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    last_error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )
