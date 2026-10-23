from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, Integer, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType


class LicenseInfo(SQLModelSerializable, table=True):
    """Deployment-level current license row. One module per row. No tenant_id."""

    __tablename__ = "license_info"

    license_code: str = Field(sa_column=Column(String(32), primary_key=True, nullable=False))
    expire_date: date | None = Field(default=None, sa_column=Column(Date, nullable=True))
    days_remaining: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    display_state: str = Field(sa_column=Column(String(16), nullable=False))
    source_status: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    checked_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    extra: dict | None = Field(default_factory=dict, sa_column=Column(JsonType, nullable=True))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )
