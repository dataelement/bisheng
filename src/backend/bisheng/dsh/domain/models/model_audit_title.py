"""Authoritative short-text titles, independent of rebuildable audit directories."""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, PreciseDateTime


class DshModelAuditConversationTitle(SQLModelSerializable, table=True):
    __tablename__ = "dsh_model_audit_conversation_title"

    conversation_key: str = Field(sa_column=Column(String(64), primary_key=True))
    tenant_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    conversation_id: str = Field(sa_column=Column(String(256), nullable=False))
    title: str = Field(sa_column=Column(String(512), nullable=False))
    title_event_seq: int = Field(sa_column=Column(BigInteger, nullable=False))
    received_at: datetime = Field(sa_column=Column(PreciseDateTime(), nullable=False))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=text("CURRENT_TIMESTAMP")
        ),
    )
