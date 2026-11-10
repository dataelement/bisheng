"""Platform-owned desktop sessions; no commercial seat or external database."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, String, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class DshSession(SQLModelSerializable, table=True):
    __tablename__ = "dsh_session"
    __table_args__ = (
        UniqueConstraint("auth_id", name="uq_dsh_local_auth"),
        Index("ix_dsh_local_user", "tenant_id", "user_id", "session_id"),
        CheckConstraint("version >= 1", name="ck_dsh_local_version"),
        CheckConstraint("state IN ('ACTIVE','REVOKED')", name="ck_dsh_local_state"),
    )
    session_id: str = Field(sa_column=Column(String(36), primary_key=True))
    tenant_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    auth_id: str = Field(sa_column=Column(String(36), nullable=False))
    version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    state: str = Field(default="ACTIVE", sa_column=Column(String(16), nullable=False))
    device_label: str | None = Field(default=None, sa_column=Column(String(100)))
    client_version: str | None = Field(default=None, sa_column=Column(String(64)))
    created_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime, nullable=False))


class DshRefreshToken(SQLModelSerializable, table=True):
    __tablename__ = "dsh_refresh_token"
    __table_args__ = (
        UniqueConstraint("session_id", "generation", name="uq_dsh_local_refresh_generation"),
        Index("ix_dsh_local_refresh_session", "tenant_id", "session_id"),
        CheckConstraint("state IN ('ACTIVE','USED','REVOKED')", name="ck_dsh_local_refresh_state"),
        CheckConstraint("generation >= 1", name="ck_dsh_local_refresh_generation"),
    )
    token_hash: str = Field(sa_column=Column(String(64), primary_key=True))
    tenant_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    session_id: str = Field(sa_column=Column(String(36), nullable=False))
    generation: int = Field(sa_column=Column(BigInteger, nullable=False))
    state: str = Field(default="ACTIVE", sa_column=Column(String(16), nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
