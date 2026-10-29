"""Tenant-owned model visibility and model-independent personal allowances."""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType


class ModelVisibility(SQLModelSerializable, table=True):
    __tablename__ = "dsh_model_visibility"
    __table_args__ = (UniqueConstraint("tenant_id", "model_id", name="uq_dsh_visibility_model"),)

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    )
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    model_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    credit_rate: int = Field(default=100, sa_column=Column(BigInteger, nullable=False, server_default=text("100")))
    everyone: bool = Field(default=False)
    subjects: list[dict] = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))
    version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    updated_by: int = Field(sa_column=Column(BigInteger, nullable=False))
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=text("CURRENT_TIMESTAMP")
        ),
    )


class CreditRule(SQLModelSerializable, table=True):
    __tablename__ = "dsh_credit_rule"
    __table_args__ = (UniqueConstraint("tenant_id", "subject_type", "subject_id", name="uq_dsh_credit_subject"),)

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    )
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    subject_type: str = Field(sa_column=Column(String(16), nullable=False))
    subject_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    monthly_token_limit: int = Field(sa_column=Column(BigInteger, nullable=False))
    enabled: bool = Field(default=True)
    version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    updated_by: int = Field(sa_column=Column(BigInteger, nullable=False))
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=text("CURRENT_TIMESTAMP")
        ),
    )


class UnifiedPolicyAudit(SQLModelSerializable, table=True):
    __tablename__ = "dsh_unified_policy_audit"

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    )
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    actor_user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    resource: str = Field(sa_column=Column(String(128), nullable=False))
    before_values: dict | None = Field(default=None, sa_column=Column(JsonType))
    after_values: dict = Field(sa_column=Column(JsonType, nullable=False))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )


class PersonalLedgerState(SQLModelSerializable, table=True):
    """Durable recovery generation, independent of visibility and credit rules."""

    __tablename__ = "dsh_personal_ledger_state"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_dsh_personal_ledger"),)
    id: int | None = Field(
        default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    )
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    quota_epoch: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
