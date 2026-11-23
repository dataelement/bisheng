"""OAuth 2.0 / OIDC session and refresh token models (Dual-DB MySQL + DM8 compatible)."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, String, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class OAuth2Session(SQLModelSerializable, table=True):
    __tablename__ = "oauth2_session"
    __table_args__ = (
        Index("ix_oauth2_session_client_user", "client_id", "tenant_id", "user_id"),
        CheckConstraint("state IN ('ACTIVE','REVOKED')", name="ck_oauth2_session_state"),
    )

    session_id: str = Field(sa_column=Column(String(36), primary_key=True))
    client_id: str = Field(sa_column=Column(String(128), nullable=False))
    tenant_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    scope: str = Field(default="openid profile", sa_column=Column(String(512), nullable=False))
    state: str = Field(default="ACTIVE", sa_column=Column(String(16), nullable=False))
    device_name: str | None = Field(default=None, sa_column=Column(String(128), nullable=True))
    created_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    revoked_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))


class OAuth2RefreshToken(SQLModelSerializable, table=True):
    __tablename__ = "oauth2_refresh_token"
    __table_args__ = (
        UniqueConstraint("session_id", "generation", name="uq_oauth2_refresh_generation"),
        Index("ix_oauth2_refresh_session", "session_id", "state"),
        CheckConstraint("state IN ('ACTIVE','USED','REVOKED')", name="ck_oauth2_refresh_state"),
        CheckConstraint("generation >= 1", name="ck_oauth2_refresh_generation"),
    )

    token_hash: str = Field(sa_column=Column(String(64), primary_key=True))
    session_id: str = Field(sa_column=Column(String(36), nullable=False))
    client_id: str = Field(sa_column=Column(String(128), nullable=False))
    tenant_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    generation: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    state: str = Field(default="ACTIVE", sa_column=Column(String(16), nullable=False))
    used_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    expires_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
