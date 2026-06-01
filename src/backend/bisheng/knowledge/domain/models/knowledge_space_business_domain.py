from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, delete, text
from sqlmodel import Field, col, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class KnowledgeSpaceBusinessDomainCodeEnum(str, Enum):
    PP = "PP"
    QM = "QM"
    PM = "PM"
    EM = "EM"
    SA = "SA"
    EN = "EN"
    IM = "IM"
    RD = "RD"
    MM = "MM"
    SD = "SD"
    FI = "FI"
    HR = "HR"
    IT = "IT"


class KnowledgeSpaceBusinessDomainBase(SQLModelSerializable):
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("1"),
            index=True,
            comment="Tenant ID",
        ),
    )
    space_id: int = Field(
        sa_column=Column(
            ForeignKey("knowledge.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
            comment="Knowledge space id",
        ),
    )
    domain_code: KnowledgeSpaceBusinessDomainCodeEnum = Field(
        sa_column=Column(String(16), nullable=False, comment="业务域编码"),
    )
    created_by: int = Field(default=0, index=True, description="Creator user id")
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


class KnowledgeSpaceBusinessDomain(KnowledgeSpaceBusinessDomainBase, table=True):
    __tablename__ = "knowledge_space_business_domain"
    __table_args__ = (
        UniqueConstraint("space_id", "domain_code", name="uk_ksbd_space_domain"),
        Index("idx_ksbd_tenant_domain", "tenant_id", "domain_code"),
        Index("idx_ksbd_space", "space_id"),
    )

    id: int | None = Field(default=None, primary_key=True)


class KnowledgeSpaceBusinessDomainDao:
    @classmethod
    async def areplace_for_space(
        cls,
        *,
        tenant_id: int,
        space_id: int,
        domain_codes: list[str],
        created_by: int,
    ) -> None:
        async with get_async_db_session() as session:
            await session.exec(
                delete(KnowledgeSpaceBusinessDomain).where(col(KnowledgeSpaceBusinessDomain.space_id) == space_id)
            )
            rows = [
                KnowledgeSpaceBusinessDomain(
                    tenant_id=tenant_id,
                    space_id=space_id,
                    domain_code=KnowledgeSpaceBusinessDomainCodeEnum(code),
                    created_by=created_by,
                )
                for code in domain_codes
            ]
            if rows:
                session.add_all(rows)
            await session.commit()

    @classmethod
    async def alist_codes_by_space_id(cls, space_id: int) -> list[str]:
        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(KnowledgeSpaceBusinessDomain.domain_code)
                    .where(KnowledgeSpaceBusinessDomain.space_id == space_id)
                    .order_by(KnowledgeSpaceBusinessDomain.id.asc())
                )
            ).all()
            return [str(getattr(row, "value", row)) for row in rows]
