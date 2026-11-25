"""Per-tenant tool pricing configuration for F001 credit billing extension."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class DshToolPricing(SQLModelSerializable, table=True):
    """Unified tool pricing record keyed by (tenant_id, tool_id)."""

    __tablename__ = "dsh_tool_pricing"
    __table_args__ = (
        UniqueConstraint("tenant_id", "tool_id", name="uq_dsh_tool_pricing_tenant_tool"),
        CheckConstraint("pricing_mode IN ('MONEY', 'CREDITS')", name="ck_dsh_tool_pricing_mode"),
        CheckConstraint("currency IS NULL OR currency IN ('CNY', 'USD')", name="ck_dsh_tool_pricing_currency"),
        CheckConstraint("price_micro >= 0", name="ck_dsh_tool_pricing_price"),
        CheckConstraint("call_count >= 1 AND call_count <= 1000000", name="ck_dsh_tool_pricing_call_count"),
        CheckConstraint("version >= 1", name="ck_dsh_tool_pricing_version"),
    )
    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    tool_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    pricing_mode: str = Field(default="CREDITS", sa_column=Column(String(16), nullable=False, server_default=text("'CREDITS'")))
    currency: str | None = Field(default=None, sa_column=Column(String(3), nullable=True))
    price_micro: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    call_count: int = Field(default=1, sa_column=Column(BigInteger, nullable=False, server_default=text("1")))
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
