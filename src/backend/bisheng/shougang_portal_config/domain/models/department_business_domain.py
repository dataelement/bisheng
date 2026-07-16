"""Exact department-to-business-domain bindings for portal recommendation."""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class DepartmentBusinessDomain(SQLModelSerializable, table=True):
    __tablename__ = "department_business_domain"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("1"),
            comment="Tenant ID",
        ),
    )
    department_id: int = Field(
        sa_column=Column(Integer, nullable=False, comment="Exact department ID"),
    )
    business_domain_code: str = Field(
        sa_column=Column(String(16), nullable=False, comment="Normalized business domain code"),
    )
    create_user: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment="Latest configuring user ID"),
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

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "department_id",
            "business_domain_code",
            name="uk_dept_business_domain",
        ),
        Index("ix_dbd_tenant_department", "tenant_id", "department_id"),
        Index("ix_dbd_tenant_domain", "tenant_id", "business_domain_code"),
    )
