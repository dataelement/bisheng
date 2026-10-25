"""Encrypted owner environment asset; execution state lives in RuntimeOperation."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, LargeText


class AppSecretConfig(SQLModelSerializable, table=True):
    __tablename__ = "app_secret_config"
    __table_args__ = (CheckConstraint("revision >= 0", name="ck_app_secret_revision"),)

    app_id: str = Field(primary_key=True)
    tenant_id: int | None = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    revision: int = Field(default=0, nullable=False)
    values_ciphertext: str = Field(sa_column=Column(LargeText, nullable=False))
    updated_by: int = Field(nullable=False)
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )
