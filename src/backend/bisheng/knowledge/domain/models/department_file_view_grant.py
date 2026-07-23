from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class DepartmentFileViewGrantStatus:
    ACTIVE = "active"
    REVOKED = "revoked"
    INVALIDATED = "invalidated"


class DepartmentFileViewGrant(SQLModelSerializable, table=True):
    __tablename__ = "department_file_view_grant"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "space_id",
            "file_id",
            name="uk_dfvg_tenant_user_space_file",
        ),
        Index("idx_dfvg_tenant_user_status", "tenant_id", "user_id", "status"),
        Index(
            "idx_dfvg_tenant_space_file_status",
            "tenant_id",
            "space_id",
            "file_id",
            "status",
        ),
        Index(
            "idx_dfvg_tenant_department_status",
            "tenant_id",
            "department_id",
            "status",
        ),
        Index("idx_dfvg_approval_instance", "approval_instance_id"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, index=True),
    )
    user_id: int = Field(sa_column=Column(Integer, nullable=False))
    space_id: int = Field(sa_column=Column(Integer, nullable=False))
    file_id: int = Field(sa_column=Column(Integer, nullable=False))
    department_id: int = Field(sa_column=Column(Integer, nullable=False))
    approval_instance_id: int = Field(sa_column=Column(Integer, nullable=False))
    grant_source: str = Field(
        default="approval_instance",
        sa_column=Column(
            String(32),
            nullable=False,
            server_default=text("'approval_instance'"),
        ),
    )
    status: str = Field(
        default=DepartmentFileViewGrantStatus.ACTIVE,
        sa_column=Column(
            String(16),
            nullable=False,
            server_default=text("'active'"),
        ),
    )
    granted_at: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    revoked_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    revoked_by: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    revoked_reason: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    invalidated_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    invalidated_reason: str | None = Field(
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
