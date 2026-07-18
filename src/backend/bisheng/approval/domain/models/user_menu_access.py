from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, select, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class UserMenuAccessStatus:
    ACTIVE = 'active'
    REVOKED = 'revoked'


class UserMenuAccessBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=False, index=True))
    user_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    menu_key: str = Field(sa_column=Column(String(128), nullable=False, index=True))
    menu_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    grant_source: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    grant_instance_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True, index=True))
    status: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    revoked_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    revoked_by_user_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True, index=True))
    revoked_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class UserMenuAccess(UserMenuAccessBase, table=True):
    __tablename__ = 'user_menu_access'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'user_id', 'menu_key', 'grant_source', name='uq_user_menu_access_grant'),
    )

    id: Optional[int] = Field(default=None, primary_key=True)


class UserMenuAccessDao(UserMenuAccessBase):
    @classmethod
    async def aget_active_menu_keys(cls, tenant_id: int, user_id: int) -> list[str]:
        statement = select(UserMenuAccess.menu_key).where(
            UserMenuAccess.tenant_id == tenant_id,
            UserMenuAccess.user_id == user_id,
            UserMenuAccess.status == UserMenuAccessStatus.ACTIVE,
        )
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()
        return list(dict.fromkeys(rows))
