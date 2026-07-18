from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType


class MessageCitationBase(SQLModelSerializable):
    citation_id: str = Field(index=True, unique=True, max_length=128)
    message_id: int = Field(index=True)
    chat_id: str | None = Field(default=None, index=True, max_length=128)
    flow_id: str | None = Field(default=None, index=True, max_length=128)
    citation_type: str = Field(max_length=32)
    # F041: retrieval access gate — 'per_user' (F029 strict view_file) | 'shared' (config-author-scoped, toggle OFF).
    # Persisted so history resolve keeps the gate; legacy rows default to 'per_user' (strict).
    access_scope: str = Field(
        default="per_user",
        sa_column=Column(String(16), nullable=False, server_default=text("'per_user'")),
    )
    source_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    created_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )


class MessageCitation(MessageCitationBase, table=True):
    __tablename__ = "message_citation"

    id: int | None = Field(default=None, primary_key=True)
