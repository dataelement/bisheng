"""Shared user-role ORM mapping, independent of domain services."""

from datetime import datetime

from sqlalchemy import INT, Column, DateTime, Integer, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class UserRoleBase(SQLModelSerializable):
    user_id: int | None = Field(default=None, foreign_key="user.user_id", primary_key=True, ondelete="CASCADE")
    role_id: int = Field(default=None, foreign_key="role.id", primary_key=True, ondelete="CASCADE")
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )


class UserRole(UserRoleBase, table=True):
    id: int | None = Field(default=None, sa_column=Column(INT, primary_key=True, autoincrement=True))
