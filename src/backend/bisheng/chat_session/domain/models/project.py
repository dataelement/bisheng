"""Account-private project metadata; conversations retain their original owner."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, Column, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


class ChatProject(SQLModelSerializable, table=True):
    __tablename__ = "chat_project"
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    tenant_id: int = Field(index=True)
    user_id: int = Field(index=True)
    name: str = Field(max_length=30)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    deleted_at: datetime | None = None


class ChatProjectMembership(SQLModelSerializable, table=True):
    __tablename__ = "chat_project_membership"
    tenant_id: int = Field(primary_key=True, index=True)
    user_id: int = Field(primary_key=True)
    chat_id: str = Field(primary_key=True, max_length=255)
    project_id: str = Field(index=True, max_length=36)


class ChatProjectRevision(SQLModelSerializable, table=True):
    __tablename__ = "chat_project_revision"
    tenant_id: int = Field(primary_key=True, index=True)
    user_id: int = Field(primary_key=True)
    revision: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, default=0))


class ChatProjectReceipt(SQLModelSerializable, table=True):
    __tablename__ = "chat_project_receipt"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "key", name="uq_chat_project_receipt"),)
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    tenant_id: int = Field(index=True)
    user_id: int = Field(index=True)
    key: str = Field(max_length=100)
    operation: str = Field(max_length=24)
    digest: str = Field(max_length=64)
    result: dict = Field(sa_column=Column(JsonType, nullable=False))
    applied_revision: int = Field(sa_column=Column(BigInteger, nullable=False))
