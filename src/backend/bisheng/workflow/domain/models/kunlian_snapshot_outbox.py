"""昆联工作流资料同步事件持久 Outbox 模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Text, func
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class KunlianWorkflowSnapshotOutbox(SQLModelSerializable, table=True):
    """持久化的昆联工作流资料同步事件，用于异步投递、退避重试与进程重启恢复。"""

    __tablename__ = "workflow_kl_snapshot_outbox"
    __table_args__ = (
        Index("ix_wkl_snapshot_outbox_due", "status", "next_retry_at"),
        Index("ix_wkl_snapshot_outbox_flow", "tenant_id", "workflow_id"),
    )

    event_id: str = Field(primary_key=True, max_length=128)
    tenant_id: int = Field(index=True)
    workflow_id: str = Field(max_length=32)
    actor_sub: str = Field(max_length=128)
    # 序列化一次并持久化，重试时原样发送原始字节，避免触发接收端 409 冲突
    payload_json: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(default="PENDING", max_length=16)
    attempts: int = Field(default=0)
    next_retry_at: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    claimed_at: int | None = Field(default=None, sa_column=Column(BigInteger))
    delivered_at: int | None = Field(default=None, sa_column=Column(BigInteger))
    last_status_code: int | None = Field(default=None)
    last_request_id: str | None = Field(default=None, max_length=128)
    last_error: str | None = Field(default=None, max_length=255)
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=func.now())
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    )
