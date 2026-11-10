"""运行、幂等和待投递的持久事实。"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, UniqueConstraint, func
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


class KunlianWorkflowRun(SQLModelSerializable, table=True):
    __tablename__ = "workflow_kl_run"
    __table_args__ = (
        UniqueConstraint("tenant_id", "connection_id", "user_id", "key_digest", name="uq_wkl_run_key"),
        Index("ix_wkl_run_pending", "tenant_id", "connection_id", "status", "deadline_at"),
    )

    session_id: str = Field(primary_key=True, max_length=32)
    tenant_id: int
    connection_id: str = Field(max_length=128)
    user_id: int
    workflow_id: str = Field(max_length=32)
    workflow_version_id: int
    key_digest: str = Field(max_length=64)
    request_digest: str = Field(max_length=64)
    status: str = Field(max_length=16)
    claim_id: str | None = Field(default=None, max_length=32)
    accepted_at: int = Field(sa_column=Column(BigInteger, nullable=False))
    started_at: int | None = Field(default=None, sa_column=Column(BigInteger))
    finished_at: int | None = Field(default=None, sa_column=Column(BigInteger))
    deadline_at: int = Field(sa_column=Column(BigInteger, nullable=False))
    expires_at: int | None = Field(default=None, sa_column=Column(BigInteger))
    material: dict | None = Field(default=None, sa_column=Column(JsonType))
    output: dict | None = Field(default=None, sa_column=Column(JsonType))
    error: str | None = Field(default=None, max_length=64)
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=func.now())
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    )
