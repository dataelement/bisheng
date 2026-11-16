"""Durable caller request binding; F048 remains the mutation authority."""

from sqlalchemy import BigInteger, Column, Integer, String, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class KunlianGrantReceipt(SQLModelSerializable, table=True):
    __tablename__ = "kunlian_grant_receipt"
    __table_args__ = (UniqueConstraint("tenant_id", "request_key", name="uq_kunlian_grant_request"),)
    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    tenant_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    request_key: str = Field(sa_column=Column(String(64), nullable=False))
    digest: str = Field(sa_column=Column(String(64), nullable=False))
    status: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    applied_revision: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
