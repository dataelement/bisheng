"""工作流登记和创建恢复的持久事实。"""

from sqlalchemy import BigInteger, Column, Index
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


class KunlianWorkflowCreation(SQLModelSerializable, table=True):
    __tablename__ = "workflow_kl_creation"
    __table_args__ = (Index("ix_wkl_creation_flow", "tenant_id", "workflow_id", unique=True),)

    key: str = Field(primary_key=True, max_length=64)
    tenant_id: int = Field(index=True)
    user_id: int
    digest: str = Field(max_length=64)
    workflow_id: str = Field(max_length=32)
    completed: bool = False


class KunlianWorkflowStream(SQLModelSerializable, table=True):
    __tablename__ = "workflow_kl_stream"

    tenant_id: int = Field(primary_key=True)
    connection_id: str = Field(primary_key=True, max_length=128)
    sequence: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    retained_after: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))


class KunlianWorkflowVersion(SQLModelSerializable, table=True):
    __tablename__ = "workflow_kl_version"
    __table_args__ = (Index("ix_wkl_version_catalog", "tenant_id", "connection_id", "current", "workflow_id"),)

    tenant_id: int = Field(primary_key=True)
    connection_id: str = Field(primary_key=True, max_length=128)
    workflow_id: str = Field(primary_key=True, max_length=32)
    version_id: int = Field(primary_key=True)
    current: bool = False
    availability: str = Field(max_length=16)
    sequence: int = Field(sa_column=Column(BigInteger, nullable=False))
    descriptor: dict | None = Field(default=None, sa_column=Column(JsonType))
    receipt: dict | None = Field(default=None, sa_column=Column(JsonType))


class KunlianWorkflowChange(SQLModelSerializable, table=True):
    __tablename__ = "workflow_kl_change"

    tenant_id: int = Field(primary_key=True)
    connection_id: str = Field(primary_key=True, max_length=128)
    sequence: int = Field(sa_column=Column(BigInteger, primary_key=True, autoincrement=False))
    payload: dict = Field(sa_column=Column(JsonType, nullable=False))
