from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, text
from sqlmodel import JSON, Field

from bisheng.common.models.base import SQLModelSerializable


class MessageCitationBase(SQLModelSerializable):
    citation_id: str = Field(index=True, unique=True, max_length=128)
    message_id: int = Field(index=True)
    chat_id: Optional[str] = Field(default=None, index=True, max_length=128)
    flow_id: Optional[str] = Field(default=None, index=True, max_length=128)
    citation_type: str = Field(max_length=32)
    source_payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )


class MessageCitation(MessageCitationBase, table=True):
    __tablename__ = "message_citation"

    id: Optional[int] = Field(default=None, primary_key=True)
