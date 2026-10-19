"""Rebuildable conversation directory; never stores model bodies."""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, PreciseDateTime


class DshModelAuditConversation(SQLModelSerializable, table=True):
    __tablename__ = "dsh_model_audit_conversation"
    __table_args__ = (
        Index("ix_dma_conversation_list", "tenant_id", "listed_at", "conversation_key"),
        Index("ix_dma_conversation_user", "tenant_id", "user_id", "listed_at", "conversation_key"),
    )
    conversation_key: str = Field(sa_column=Column(String(64), primary_key=True))
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=text("CURRENT_TIMESTAMP")
        ),
    )
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    conversation_id: str = Field(sa_column=Column(String(1024), nullable=False))
    listed_at: datetime = Field(sa_column=Column(PreciseDateTime(), nullable=False))
    first_request_at: datetime = Field(sa_column=Column(PreciseDateTime(), nullable=False))
    last_request_at: datetime = Field(sa_column=Column(PreciseDateTime(), nullable=False))
    updated_at: datetime = Field(sa_column=Column(PreciseDateTime(), nullable=False))
    request_count: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    abnormal_count: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
