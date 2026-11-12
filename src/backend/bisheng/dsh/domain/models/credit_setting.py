"""Tenant credit settings: billing currency, credit value, exchange rate, base model (F015)."""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class DshCreditSetting(SQLModelSerializable, table=True):
    __tablename__ = "dsh_credit_setting"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_dsh_credit_setting_tenant"),)

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    )
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    currency: str = Field(sa_column=Column(String(3), nullable=False))
    credit_value_micro: int = Field(sa_column=Column(BigInteger, nullable=False))
    usd_cny_rate_micro: int = Field(sa_column=Column(BigInteger, nullable=False))
    base_model_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    updated_by: int = Field(sa_column=Column(BigInteger, nullable=False))
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=text("CURRENT_TIMESTAMP")
        ),
    )
