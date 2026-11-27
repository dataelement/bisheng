"""Exchange policy and immutable child-to-parent session links."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType


class OAuth2ExchangePolicy(SQLModelSerializable, table=True):
    __tablename__ = "oauth2_exchange_policy"
    source_client_id: str = Field(sa_column=Column(String(128), primary_key=True))
    target_client_id: str = Field(sa_column=Column(String(128), primary_key=True))
    allowed_scopes: list[str] = Field(sa_column=Column(JsonType, nullable=False))
    enabled: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))
    created_by: int = Field(sa_column=Column(BigInteger, nullable=False))
    updated_by: int = Field(sa_column=Column(BigInteger, nullable=False))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=datetime.utcnow),
    )


class OAuth2ExchangeSession(SQLModelSerializable, table=True):
    __tablename__ = "oauth2_exchange_session"
    __table_args__ = (Index("ix_oauth2_exchange_parent", "source_session_id"),)
    session_id: str = Field(sa_column=Column(String(36), primary_key=True))
    source_session_id: str = Field(sa_column=Column(String(36), nullable=False))
    source_client_id: str = Field(sa_column=Column(String(128), nullable=False))
    target_client_id: str = Field(sa_column=Column(String(128), nullable=False))
    tenant_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    issuer: str = Field(sa_column=Column(String(2048), nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
