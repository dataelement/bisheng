"""OAuth 2.0 / OIDC client registration model (Dual-DB MySQL + DM8 compatible)."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType

BUILTIN_DSH_CLIENT_ID = "dsh-desktop"
DEFAULT_ALLOWED_SCOPES = ["openid", "profile", "email", "offline_access"]
DSH_ALLOWED_SCOPES = ["openid", "profile", "email", "offline_access", "dsh"]
DEFAULT_GRANT_TYPES = ["authorization_code", "refresh_token"]


class OAuth2Client(SQLModelSerializable, table=True):
    __tablename__ = "oauth2_client"
    __table_args__ = (UniqueConstraint("client_id", name="uq_oauth2_client_id"),)

    id: int | None = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    client_id: str = Field(sa_column=Column(String(128), nullable=False))
    client_name: str = Field(sa_column=Column(String(128), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(String(512), nullable=True))
    client_type: str = Field(default="confidential", sa_column=Column(String(16), nullable=False))
    client_secret_hash: str | None = Field(default=None, sa_column=Column(String(256), nullable=True))
    redirect_uris: list[str] = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))
    allow_loopback_port: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=text("0"))
    )
    allowed_scopes: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_SCOPES),
        sa_column=Column(JsonType, nullable=False),
    )
    grant_types: list[str] = Field(
        default_factory=lambda: list(DEFAULT_GRANT_TYPES),
        sa_column=Column(JsonType, nullable=False),
    )
    require_pkce: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default=text("1")))
    require_consent: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default=text("1")))
    enabled: bool = Field(default=True, sa_column=Column(Boolean, nullable=False, server_default=text("1")))
    is_builtin: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("0")))
    access_token_ttl: int = Field(default=3600, sa_column=Column(Integer, nullable=False, server_default=text("3600")))
    refresh_token_ttl: int = Field(
        default=1209600,
        sa_column=Column(Integer, nullable=False, server_default=text("1209600")),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
            onupdate=datetime.utcnow,
        ),
    )
