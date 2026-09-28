"""Durable state for the COFCO E+ robot integration."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType, LargeText


class EPlusConnectionStatus(StrEnum):
    DISABLED = "DISABLED"
    CONNECTING = "CONNECTING"
    AUTHENTICATED = "AUTHENTICATED"
    RETRYING = "RETRYING"
    TAKEN_OVER = "TAKEN_OVER"
    ERROR = "ERROR"


class EPlusInboundStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PREPARING = "PREPARING"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REJECTED_BUSY = "REJECTED_BUSY"


class EPlusReplyStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    STREAMING = "STREAMING"
    FINISHED = "FINISHED"
    SEND_FAILED = "SEND_FAILED"


class EPlusChatType(StrEnum):
    SINGLE = "SINGLE"
    GROUP = "GROUP"


class EPlusMessageType(StrEnum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    MIXED = "MIXED"


class EPlusConversationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class EPlusTurnStatus(StrEnum):
    PREPARING = "PREPARING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


def _primary_key_column() -> Column:
    return Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )


def _tenant_column() -> Column:
    return Column(Integer, nullable=False, index=True, comment="Tenant ID")


def _create_time_column() -> Column:
    return Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


def _update_time_column() -> Column:
    return Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)


class EPlusBotConfig(SQLModelSerializable, table=True):
    __tablename__ = "eplus_bot_config"
    __table_args__ = (
        UniqueConstraint("tenant_id", "assistant_id", name="uq_eplus_bot_config_assistant"),
        UniqueConstraint("tenant_id", "bot_id", name="uq_eplus_bot_config_bot"),
        Index("ix_eplus_bot_config_target", "tenant_id", "enabled", "connection_status"),
    )

    id: int | None = Field(default=None, sa_column=_primary_key_column())
    tenant_id: int | None = Field(default=None, sa_column=_tenant_column())
    assistant_id: str = Field(sa_column=Column(String(64), nullable=False))
    bot_id: str = Field(sa_column=Column(String(128), nullable=False))
    connection_url: str = Field(sa_column=Column(String(1024), nullable=False))
    secret_ciphertext: str = Field(sa_column=Column(LargeText, nullable=False))
    credential_version: int = Field(
        default=1,
        sa_column=Column(BigInteger, nullable=False, server_default=text("1")),
    )
    ca_object_key: str | None = Field(default=None, sa_column=Column(String(512), nullable=True))
    ca_sha256: str | None = Field(default=None, sa_column=Column(CHAR(64), nullable=True))
    media_host_allowlist: list[str] = Field(
        default_factory=list,
        sa_column=Column(JsonType, nullable=False),
    )
    enabled: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    is_deleted: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, default=False))
    connection_status: str = Field(
        default=EPlusConnectionStatus.DISABLED.value,
        sa_column=Column(
            String(32),
            nullable=False,
            server_default=text("'DISABLED'"),
        ),
    )
    last_connected_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    last_error_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    last_error_code: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    scope_version: int = Field(
        default=1,
        sa_column=Column(BigInteger, nullable=False, server_default=text("1")),
    )
    created_by: int = Field(sa_column=Column(BigInteger, nullable=False))
    updated_by: int = Field(sa_column=Column(BigInteger, nullable=False))
    create_time: datetime | None = Field(default=None, sa_column=_create_time_column())
    update_time: datetime | None = Field(default=None, sa_column=_update_time_column())


class EPlusBotSpace(SQLModelSerializable, table=True):
    __tablename__ = "eplus_bot_space"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "bot_config_id",
            "space_id",
            name="uq_eplus_bot_space_binding",
        ),
        Index("ix_eplus_bot_space_space", "tenant_id", "space_id"),
    )

    id: int | None = Field(default=None, sa_column=_primary_key_column())
    tenant_id: int | None = Field(default=None, sa_column=_tenant_column())
    bot_config_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("eplus_bot_config.id"), nullable=False),
    )
    space_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    bound_by: int = Field(sa_column=Column(BigInteger, nullable=False))
    create_time: datetime | None = Field(default=None, sa_column=_create_time_column())


class EPlusInboundMessage(SQLModelSerializable, table=True):
    __tablename__ = "eplus_inbound_message"
    __table_args__ = (
        UniqueConstraint("tenant_id", "bot_id", "msgid", name="uq_eplus_inbound_message"),
        UniqueConstraint("tenant_id", "stream_id", name="uq_eplus_inbound_stream"),
        Index(
            "ix_eplus_inbound_processing",
            "tenant_id",
            "bot_config_id",
            "status",
            "received_at",
        ),
        Index(
            "ix_eplus_inbound_sender",
            "tenant_id",
            "sender_external_id",
            "status",
        ),
    )

    id: int | None = Field(default=None, sa_column=_primary_key_column())
    tenant_id: int | None = Field(default=None, sa_column=_tenant_column())
    bot_config_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("eplus_bot_config.id"), nullable=False),
    )
    bot_id: str = Field(sa_column=Column(String(128), nullable=False))
    msgid: str = Field(sa_column=Column(String(255), nullable=False))
    req_id: str = Field(sa_column=Column(String(255), nullable=False))
    stream_id: str = Field(sa_column=Column(String(255), nullable=False))
    conversation_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    turn_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    sender_external_id: str = Field(sa_column=Column(String(255), nullable=False))
    sender_user_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    chat_type: str = Field(sa_column=Column(String(16), nullable=False))
    chat_id: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    msg_type: str = Field(sa_column=Column(String(16), nullable=False))
    payload_sha256: str = Field(sa_column=Column(CHAR(64), nullable=False))
    status: str = Field(
        default=EPlusInboundStatus.RECEIVED.value,
        sa_column=Column(String(32), nullable=False, server_default=text("'RECEIVED'")),
    )
    reply_status: str = Field(
        default=EPlusReplyStatus.NOT_STARTED.value,
        sa_column=Column(String(32), nullable=False, server_default=text("'NOT_STARTED'")),
    )
    error_code: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    received_at: datetime | None = Field(default=None, sa_column=_create_time_column())
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: datetime | None = Field(default=None, sa_column=_create_time_column())
    update_time: datetime | None = Field(default=None, sa_column=_update_time_column())


class EPlusConversation(SQLModelSerializable, table=True):
    __tablename__ = "eplus_conversation"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "bot_config_id",
            "chat_type",
            "conversation_key",
            name="uq_eplus_conversation_key",
        ),
        Index("ix_eplus_conversation_recent", "tenant_id", "bot_config_id", "update_time"),
    )

    id: str = Field(sa_column=Column(String(64), primary_key=True))
    tenant_id: int | None = Field(default=None, sa_column=_tenant_column())
    bot_config_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("eplus_bot_config.id"), nullable=False),
    )
    assistant_id: str = Field(sa_column=Column(String(64), nullable=False))
    chat_type: str = Field(sa_column=Column(String(16), nullable=False))
    conversation_key: str = Field(sa_column=Column(String(255), nullable=False))
    scope_version: int = Field(sa_column=Column(BigInteger, nullable=False))
    next_turn_seq: int = Field(
        default=1,
        sa_column=Column(BigInteger, nullable=False, server_default=text("1")),
    )
    status: str = Field(
        default=EPlusConversationStatus.ACTIVE.value,
        sa_column=Column(String(16), nullable=False, server_default=text("'ACTIVE'")),
    )
    create_time: datetime | None = Field(default=None, sa_column=_create_time_column())
    update_time: datetime | None = Field(default=None, sa_column=_update_time_column())


class EPlusTurn(SQLModelSerializable, table=True):
    __tablename__ = "eplus_turn"
    __table_args__ = (
        UniqueConstraint("tenant_id", "inbound_message_id", name="uq_eplus_turn_inbound"),
        UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "turn_seq",
            name="uq_eplus_turn_sequence",
        ),
        Index(
            "ix_eplus_turn_history",
            "tenant_id",
            "conversation_id",
            "scope_version",
            "turn_seq",
        ),
        Index("ix_eplus_turn_queue", "tenant_id", "status", "queued_at"),
    )

    id: str = Field(sa_column=Column(String(64), primary_key=True))
    tenant_id: int | None = Field(default=None, sa_column=_tenant_column())
    conversation_id: str = Field(
        sa_column=Column(String(64), ForeignKey("eplus_conversation.id"), nullable=False),
    )
    inbound_message_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("eplus_inbound_message.id"), nullable=False),
    )
    turn_seq: int = Field(sa_column=Column(BigInteger, nullable=False))
    sender_user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    sender_external_id: str = Field(sa_column=Column(String(255), nullable=False))
    user_text: str | None = Field(default=None, sa_column=Column(LargeText, nullable=True))
    content_manifest: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JsonType, nullable=False),
    )
    extracted_text: str | None = Field(default=None, sa_column=Column(LargeText, nullable=True))
    scope_version: int = Field(sa_column=Column(BigInteger, nullable=False))
    scope_space_ids: list[int] = Field(
        default_factory=list,
        sa_column=Column(JsonType, nullable=False),
    )
    assistant_run_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    answer_text: str | None = Field(default=None, sa_column=Column(LargeText, nullable=True))
    status: str = Field(
        default=EPlusTurnStatus.QUEUED.value,
        sa_column=Column(String(16), nullable=False, server_default=text("'QUEUED'")),
    )
    error_code: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    queued_at: datetime | None = Field(default=None, sa_column=_create_time_column())
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: datetime | None = Field(default=None, sa_column=_create_time_column())
    update_time: datetime | None = Field(default=None, sa_column=_update_time_column())
