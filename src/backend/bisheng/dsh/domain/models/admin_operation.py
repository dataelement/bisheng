"""F062 admin operation persistence model."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType


class DshAdminOperation(SQLModelSerializable, table=True):
    """Shared durable intent, immutable audit snapshots and retry ownership."""

    __tablename__ = "dsh_admin_operation"
    __table_args__ = (
        Index("ix_dsh_operation_retry", "status", "next_retry_at"),
        Index("ix_dsh_operation_user", "tenant_id", "user_id", "create_time"),
        CheckConstraint(
            "action IN ('REVOKE','REASSIGN','UPDATE_POLICY','RECONCILE_USAGE','SYNC_PROFILE')",
            name="ck_dsh_operation_action",
        ),
        CheckConstraint("status IN ('PENDING','PROCESSING','SUCCEEDED','FAILED')", name="ck_dsh_operation_status"),
        CheckConstraint("action = 'SYNC_PROFILE' OR actor_user_id IS NOT NULL", name="ck_dsh_operation_actor"),
        CheckConstraint(
            "action NOT IN ('REVOKE','REASSIGN') OR expected_grant_version IS NOT NULL", name="ck_dsh_operation_grant"
        ),
        CheckConstraint(
            "action <> 'UPDATE_POLICY' OR expected_policy_version IS NOT NULL", name="ck_dsh_operation_policy"
        ),
        CheckConstraint(
            "action <> 'RECONCILE_USAGE' OR expected_event_version IS NOT NULL", name="ck_dsh_operation_event"
        ),
        CheckConstraint("attempts >= 0 AND lease_generation >= 0", name="ck_dsh_operation_retry"),
    )
    operation_id: str = Field(sa_column=Column(String(36), primary_key=True))
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=text("CURRENT_TIMESTAMP")
        ),
    )
    actor_user_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    action: str = Field(sa_column=Column(String(16), nullable=False))
    expected_grant_version: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    expected_policy_version: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    expected_event_version: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    payload_hash: str = Field(sa_column=Column(String(64), nullable=False))
    payload: dict[str, Any] = Field(sa_column=Column(JsonType, nullable=False))
    before_values: dict[str, Any] | None = Field(default=None, sa_column=Column(JsonType, nullable=True))
    after_values: dict[str, Any] | None = Field(default=None, sa_column=Column(JsonType, nullable=True))
    committed_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    effective_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    status: str = Field(
        default="PENDING", sa_column=Column(String(16), nullable=False, server_default=text("'PENDING'"))
    )
    attempts: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    next_retry_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    lease_until: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    lease_generation: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    result_code: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    result_payload: dict[str, Any] | None = Field(default=None, sa_column=Column(JsonType, nullable=True))
