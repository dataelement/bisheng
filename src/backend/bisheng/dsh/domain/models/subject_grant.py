"""Frozen member selection and recoverable subject grant intent."""

from sqlalchemy import BigInteger, Column, Index, String
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


class DshSubjectGrant(SQLModelSerializable, table=True):
    __tablename__ = "dsh_subject_grant"
    __table_args__ = (Index("ix_dsh_subject_grant_scope", "tenant_id", "subject_type", "subject_id", "model_id"),)
    operation_id: str = Field(sa_column=Column(String(36), primary_key=True))
    tenant_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    actor_user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    subject_type: str = Field(sa_column=Column(String(16), nullable=False))
    subject_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    model_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    status: str = Field(sa_column=Column(String(16), nullable=False))
    payload: dict = Field(sa_column=Column(JsonType, nullable=False))
    result: dict | None = Field(default=None, sa_column=Column(JsonType, nullable=True))
