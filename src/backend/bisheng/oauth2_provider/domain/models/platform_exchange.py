"""Standalone first-party exchange links and explicit user consent, auto-discovered on upgrade."""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType


class OAuth2PlatformExchangeSession(SQLModelSerializable, table=True):
    __tablename__ = "oauth2_platform_exchange_session"
    session_id: str = Field(sa_column=Column(String(36), primary_key=True))
    source_client_id: str = Field(sa_column=Column(String(128), nullable=False))
    target_client_id: str = Field(sa_column=Column(String(128), nullable=False))
    target_registration_id: int = Field(sa_column=Column(Integer, nullable=False))
    tenant_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    issuer: str = Field(sa_column=Column(String(512), nullable=False))
    source_reference: dict = Field(sa_column=Column(JsonType, nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=datetime.utcnow),
    )


class OAuth2UserConsent(SQLModelSerializable, table=True):
    __tablename__ = "oauth2_user_consent"
    client_registration_id: int = Field(sa_column=Column(Integer, primary_key=True))
    user_id: int = Field(sa_column=Column(BigInteger, primary_key=True))
    tenant_id: int = Field(sa_column=Column(BigInteger, primary_key=True, index=True))
    client_id: str = Field(sa_column=Column(String(128), nullable=False))
    scopes: list[str] = Field(sa_column=Column(JsonType, nullable=False))
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT, onupdate=datetime.utcnow),
    )
