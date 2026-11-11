"""Instance-wide account reservations and the identity creation lock (F011)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class UserAccountReservation(SQLModelSerializable, table=True):
    __tablename__ = "user_account_reservation"

    account_key: str = Field(sa_column=Column(String(64), primary_key=True))
    user_id: int = Field(unique=True, index=True)
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )


class UserIdentityWriteGuard(SQLModelSerializable, table=True):
    __tablename__ = "user_identity_write_guard"

    id: int = Field(primary_key=True)
