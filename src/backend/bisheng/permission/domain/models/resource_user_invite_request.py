from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType

RESOURCE_USER_INVITE_SCENARIO_CODE = "resource_user_invite_confirmation"
RESOURCE_USER_INVITE_REQUEST_TYPE = "resource_user_invite_request"


class ResourceUserInviteExecutionState:
    AWAITING_APPROVAL = "awaiting_approval"
    QUEUED = "queued"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"
    CLOSED = "closed"


class ResourceUserInviteRequestBase(SQLModelSerializable):
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger,
            nullable=False,
            server_default=text("1"),
            index=True,
        ),
    )
    business_key: str = Field(sa_column=Column(String(255), nullable=False))
    active_marker: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False, server_default=text("0")),
    )
    request_fingerprint: str = Field(sa_column=Column(String(64), nullable=False))

    resource_type: str = Field(sa_column=Column(String(64), nullable=False))
    resource_id: str = Field(sa_column=Column(String(128), nullable=False))
    resource_name: str = Field(sa_column=Column(String(255), nullable=False))
    inviter_user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    inviter_user_name: str = Field(sa_column=Column(String(255), nullable=False))
    target_user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    target_user_name: str = Field(sa_column=Column(String(255), nullable=False))
    relation: str = Field(sa_column=Column(String(64), nullable=False))
    model_id: str | None = Field(default=None, sa_column=Column(String(128), nullable=True))
    include_children: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    role_snapshot: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    role_fingerprint: str = Field(sa_column=Column(String(64), nullable=False))

    approval_instance_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    decision_event_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    execution_state: str = Field(
        default=ResourceUserInviteExecutionState.AWAITING_APPROVAL,
        sa_column=Column(
            String(32),
            nullable=False,
            server_default=text("'awaiting_approval'"),
        ),
    )
    execution_token: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    error_summary: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    result_snapshot: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))

    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class ResourceUserInviteRequest(ResourceUserInviteRequestBase, table=True):
    __tablename__ = "resource_user_invite_request"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "business_key",
            "active_marker",
            name="uq_resource_user_invite_active",
        ),
        UniqueConstraint(
            "tenant_id",
            "approval_instance_id",
            name="uq_resource_user_invite_instance",
        ),
        UniqueConstraint(
            "tenant_id",
            "decision_event_id",
            name="uq_resource_user_invite_event",
        ),
        Index(
            "idx_resource_user_invite_resource",
            "tenant_id",
            "resource_type",
            "resource_id",
            "execution_state",
            "create_time",
            "id",
        ),
        Index(
            "idx_resource_user_invite_target",
            "tenant_id",
            "target_user_id",
            "execution_state",
            "create_time",
            "id",
        ),
        Index(
            "idx_resource_user_invite_execution",
            "tenant_id",
            "execution_state",
            "update_time",
            "id",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger().with_variant(Integer, "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
    )
