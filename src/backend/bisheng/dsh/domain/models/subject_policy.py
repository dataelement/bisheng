"""Department and role policies for DSH model access."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType


class DshSubjectPolicy(SQLModelSerializable, table=True):
    """One independently versioned department/role grant for a model."""

    __tablename__ = "dsh_subject_policy"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "subject_type", "subject_id", "model_id", name="uq_dsh_subject_policy_subject_model"
        ),
        Index("ix_dsh_subject_policy_model", "tenant_id", "model_id", "subject_type", "subject_id"),
        Index("ix_dsh_subject_policy_subject", "tenant_id", "subject_type", "subject_id", "enabled"),
        CheckConstraint("subject_type IN ('DEPARTMENT','ROLE')", name="ck_dsh_subject_policy_type"),
        CheckConstraint(
            "subject_id > 0 AND model_id > 0 AND monthly_token_limit >= 0 AND enabled IN (0,1)",
            name="ck_dsh_subject_policy_values",
        ),
        CheckConstraint("version >= 1", name="ck_dsh_subject_policy_version"),
    )
    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    subject_type: str = Field(sa_column=Column(String(16), nullable=False))
    subject_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    model_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    monthly_token_limit: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    enabled: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False, server_default=text("1")))
    updated_by: int = Field(sa_column=Column(BigInteger, nullable=False))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=text("CURRENT_TIMESTAMP")
        ),
    )


class DshSubjectPolicyAudit(SQLModelSerializable, table=True):
    """Immutable actor and before/after evidence for every subject policy write."""

    __tablename__ = "dsh_subject_policy_audit"
    __table_args__ = (
        Index("ix_dsh_subject_policy_audit_subject", "tenant_id", "subject_type", "subject_id", "model_id"),
        CheckConstraint("subject_type IN ('DEPARTMENT','ROLE')", name="ck_dsh_subject_policy_audit_type"),
    )
    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    subject_type: str = Field(sa_column=Column(String(16), nullable=False))
    subject_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    model_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    actor_user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    before_values: dict | None = Field(default=None, sa_column=Column(JsonType, nullable=True))
    after_values: dict = Field(sa_column=Column(JsonType, nullable=False))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
