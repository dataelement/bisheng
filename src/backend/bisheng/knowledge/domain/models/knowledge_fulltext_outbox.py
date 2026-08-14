"""合并式全文索引 Outbox 模型。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    JsonType,
    LargeText,
)

_BIGINT_PK = BigInteger().with_variant(Integer(), "sqlite")


class KnowledgeFulltextAggregateType(str, Enum):
    FILE = "file"
    KNOWLEDGE = "knowledge"


class KnowledgeFulltextDesiredAction(str, Enum):
    SYNC_CURRENT = "sync_current"
    DELETE_CURRENT = "delete_current"
    FANOUT_CURRENT = "fanout_current"
    DELETE_SCOPE = "delete_scope"


class KnowledgeFulltextOutboxStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


class KnowledgeFulltextOutbox(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_fulltext_outbox"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "aggregate_type",
            "aggregate_id",
            name="uk_knowledge_fulltext_outbox_aggregate",
        ),
        Index(
            "ix_kfo_dispatch",
            "status",
            "next_retry_at",
            "lease_until",
            "update_time",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(_BIGINT_PK, primary_key=True, autoincrement=True),
    )
    tenant_id: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default=text("1")))
    aggregate_type: str = Field(sa_column=Column(String(16), nullable=False))
    aggregate_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    knowledge_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    desired_action: str = Field(sa_column=Column(String(32), nullable=False))
    desired_revision: int = Field(default=1, sa_column=Column(BigInteger, nullable=False, server_default=text("1")))
    applied_revision: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default=text("0")))
    trigger_type: str = Field(sa_column=Column(String(64), nullable=False))
    status: str = Field(
        default=KnowledgeFulltextOutboxStatus.PENDING.value,
        sa_column=Column(String(16), nullable=False, server_default=text("'pending'")),
    )
    retry_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default=text("0")))
    max_retries: int = Field(default=8, sa_column=Column(Integer, nullable=False, server_default=text("8")))
    next_retry_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    lease_owner: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    lease_until: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    fanout_cursor: dict | None = Field(default=None, sa_column=Column(JsonType, nullable=True))
    payload_snapshot: dict | None = Field(default=None, sa_column=Column(JsonType, nullable=True))
    error_summary: str | None = Field(default=None, sa_column=Column(LargeText, nullable=True))
    last_success_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )
