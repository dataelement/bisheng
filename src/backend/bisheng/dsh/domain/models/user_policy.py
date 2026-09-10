"""F062 user policy persistence model."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class DshUserPolicy(SQLModelSerializable, table=True):
    """One independently versioned user/model grant; revocation retains its version."""

    __tablename__ = "dsh_user_policy"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "model_id", name="uq_dsh_policy_user_model"),
        Index("ix_dsh_policy_model_users", "tenant_id", "model_id", "enabled", "user_id"),
        CheckConstraint("model_id > 0 AND monthly_token_limit >= 0 AND enabled IN (0,1)", name="ck_dsh_policy_model"),
        CheckConstraint("version >= 0 AND quota_epoch >= 1", name="ck_dsh_policy_counters"),
        CheckConstraint("quota_sync_state IN ('PENDING','READY','FROZEN')", name="ck_dsh_policy_sync"),
    )
    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
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
    model_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    monthly_token_limit: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    enabled: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))

    version: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    quota_sync_state: str = Field(
        default="PENDING", sa_column=Column(String(16), nullable=False, server_default=text("'PENDING'"))
    )
    quota_epoch: int = Field(default=1, sa_column=Column(BigInteger, nullable=False, server_default=text("1")))
    updated_by: int = Field(sa_column=Column(BigInteger, nullable=False))
    pending_operation_id: str | None = Field(default=None, sa_column=Column(String(36), nullable=True))
