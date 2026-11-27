"""Platform-owned login state. Refresh credentials are never persisted in plaintext."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, Integer, String, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class PlatformSession(SQLModelSerializable, table=True):
    __tablename__ = "platform_session"
    __table_args__ = (
        Index("ix_platform_session_user", "user_id", "tenant_id"),
        CheckConstraint("state IN ('ACTIVE','REVOKED')", name="ck_platform_session_state"),
        CheckConstraint("version >= 1", name="ck_platform_session_version"),
    )
    # Private database-generated ordering survives same-second timestamps and
    # issuer clock skew across API instances. Public identity remains the sid.
    issuance_order: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    session_id: str = Field(sa_column=Column(String(32), nullable=False, unique=True))
    tenant_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    create_time: datetime = Field(
        default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False, default=datetime.utcnow)
    )
    update_time: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow),
    )
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    token_version: int = Field(default=0, nullable=False)
    access_ttl_seconds: int = Field(default=2592000, nullable=False)
    idle_ttl_seconds: int = Field(default=7776000, nullable=False)
    refresh_grace_seconds: int = Field(default=86400, nullable=False)
    version: int = Field(default=1, sa_column=Column(BigInteger, nullable=False))
    state: str = Field(default="ACTIVE", max_length=16, nullable=False)
    delivery_state: str = Field(default="BOUND", max_length=32, nullable=False)
    client_id: str = Field(max_length=64, nullable=False)
    device_label: str | None = Field(default=None, max_length=100)
    client_version: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    last_activity_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    absolute_expires_at: datetime | None = Field(default=None, sa_column=Column(DateTime))
    parent_session_id: str | None = Field(default=None, max_length=32)


class PlatformRefreshToken(SQLModelSerializable, table=True):
    __tablename__ = "platform_refresh_token"
    __table_args__ = (
        UniqueConstraint("session_id", "generation", name="uq_platform_refresh_generation"),
        Index("ix_platform_refresh_session", "tenant_id", "session_id", "state"),
        CheckConstraint("state IN ('ACTIVE','USED','REVOKED')", name="ck_platform_refresh_state"),
        CheckConstraint("generation >= 1", name="ck_platform_refresh_generation"),
    )
    token_hash: str = Field(sa_column=Column(String(64), primary_key=True))
    tenant_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    create_time: datetime = Field(
        default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False, default=datetime.utcnow)
    )
    update_time: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow),
    )
    session_id: str = Field(max_length=32, nullable=False)
    generation: int = Field(sa_column=Column(BigInteger, nullable=False))
    state: str = Field(default="ACTIVE", max_length=16, nullable=False)
    used_at: datetime | None = Field(default=None, sa_column=Column(DateTime))
    expires_at: datetime = Field(sa_column=Column(DateTime, nullable=False))


class PlatformWebTicket(SQLModelSerializable, table=True):
    __tablename__ = "platform_web_ticket"
    token_hash: str = Field(sa_column=Column(String(64), primary_key=True))
    tenant_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    create_time: datetime = Field(
        default_factory=datetime.utcnow, sa_column=Column(DateTime, nullable=False, default=datetime.utcnow)
    )
    update_time: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow),
    )
    session_id: str = Field(max_length=32, nullable=False)
    host_session_id: str = Field(max_length=32, nullable=False)
    origin: str = Field(max_length=512, nullable=False)
    expires_at: datetime = Field(sa_column=Column(DateTime, nullable=False, index=True))
    consumed: bool = Field(default=False, nullable=False)
