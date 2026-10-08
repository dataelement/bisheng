"""F062 monthly usage persistence model."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class DshMonthlyUsage(SQLModelSerializable, table=True):
    """Durable projection, never an authorization fallback for a lost ledger."""

    __tablename__ = "dsh_monthly_usage"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "usage_month", "model_id", name="uq_dsh_usage_user_model_month"),
        CheckConstraint("used_tokens >= 0 AND version >= 0", name="ck_dsh_usage_counters"),
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
    usage_month: str = Field(sa_column=Column(String(7), nullable=False))
    billing_timezone: str = Field(sa_column=Column(String(64), nullable=False))
    used_tokens: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    version: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    projected_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
