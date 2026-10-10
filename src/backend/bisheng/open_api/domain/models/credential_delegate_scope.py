from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable

DELEGATE_SUBJECT_USER = "user"
DELEGATE_SUBJECT_DEPARTMENT = "department"
DELEGATE_SUBJECT_TYPES = frozenset({DELEGATE_SUBJECT_USER, DELEGATE_SUBJECT_DEPARTMENT})


class ApiCredentialDelegateScope(SQLModelSerializable, table=True):
    __tablename__ = "api_credential_delegate_scope"
    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('user', 'department')",
            name="ck_api_credential_delegate_scope_type",
        ),
        UniqueConstraint(
            "credential_id",
            "subject_type",
            "subject_id",
            name="uk_api_credential_delegate_scope_subject",
        ),
        Index("idx_api_credential_delegate_scope_tenant_credential", "tenant_id", "credential_id"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    tenant_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    credential_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    subject_type: str = Field(sa_column=Column(String(32), nullable=False))
    subject_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
