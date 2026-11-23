"""Phone refresh sessions. The raw refresh token is never stored."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, String, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class DshMobileSession(SQLModelSerializable, table=True):
    __tablename__ = "dsh_mobile_session"
    __table_args__ = (
        Index("ix_dsh_mobile_session_user", "tenant_id", "user_id", "session_id"),
        CheckConstraint("state IN ('ACTIVE','REVOKED')", name="ck_dsh_mobile_session_state"),
    )
    session_id: str = Field(sa_column=Column(String(36), primary_key=True))
    tenant_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    token_version: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    state: str = Field(default="ACTIVE", sa_column=Column(String(16), nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    last_access_token_hash: str | None = Field(default=None, sa_column=Column(String(64)))


class DshMobileRefreshToken(SQLModelSerializable, table=True):
    __tablename__ = "dsh_mobile_refresh_token"
    __table_args__ = (
        UniqueConstraint("session_id", "generation", name="uq_dsh_mobile_refresh_generation"),
        Index("ix_dsh_mobile_refresh_session", "tenant_id", "session_id"),
        CheckConstraint("state IN ('ACTIVE','USED','REVOKED')", name="ck_dsh_mobile_refresh_state"),
        CheckConstraint("generation >= 1", name="ck_dsh_mobile_refresh_generation"),
    )
    token_hash: str = Field(sa_column=Column(String(64), primary_key=True))
    tenant_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    session_id: str = Field(sa_column=Column(String(36), nullable=False))
    generation: int = Field(sa_column=Column(BigInteger, nullable=False))
    state: str = Field(default="ACTIVE", sa_column=Column(String(16), nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
