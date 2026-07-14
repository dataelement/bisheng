from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, Integer, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType

class MessageCitationBase(SQLModelSerializable):
    citation_id: str = Field(index=True, unique=True, max_length=128)
    message_id: int = Field(index=True)
    chat_id: Optional[str] = Field(default=None, index=True, max_length=128)
    flow_id: Optional[str] = Field(default=None, index=True, max_length=128)
    citation_type: str = Field(max_length=32)
    source_payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    created_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )


class MessageCitation(MessageCitationBase, table=True):
    __tablename__ = "message_citation"

    id: Optional[int] = Field(default=None, primary_key=True)


class MessageCitationRelationBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("1"),
            index=True,
            comment="Tenant ID",
        ),
    )
    message_id: int = Field(index=True)
    citation_id: str = Field(index=True, max_length=128)
    created_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )


class MessageCitationRelation(MessageCitationRelationBase, table=True):
    """Associate one globally stored citation with one persisted chat message."""

    __tablename__ = "message_citation_relation"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "citation_id",
            name="uq_msg_citation_rel_message_citation",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
