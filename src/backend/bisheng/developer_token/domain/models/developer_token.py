from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, LargeText


class DeveloperToken(SQLModelSerializable, table=True):
    __tablename__ = "developer_token"

    id: int | None = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    tenant_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True, comment="Bound tenant ID"),
    )
    user_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True, comment="Bound user ID"),
    )
    name: str = Field(
        sa_column=Column(String(128), nullable=False, comment="Developer token name"),
    )
    token_hash: str = Field(
        sa_column=Column(String(128), nullable=False, unique=True, index=True, comment="HMAC token hash"),
    )
    token_ciphertext: str = Field(
        sa_column=Column(LargeText, nullable=False, comment="Encrypted plaintext token"),
    )
    token_prefix: str = Field(
        sa_column=Column(String(16), nullable=False, index=True, comment="Display token prefix"),
    )
    enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("1"), comment="Whether token is enabled"),
    )
    override_ip_whitelist: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    ip_whitelist: str | None = Field(
        default=None,
        sa_column=Column(LargeText, nullable=True, comment="Newline/comma separated IP or CIDR rules"),
    )
    override_rate_limit: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("0")),
    )
    rate_limit_per_minute: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment="Per-minute request limit"),
    )
    last_used_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    last_used_ip: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    created_by: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    updated_by: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    logic_delete: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0"), index=True),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )
