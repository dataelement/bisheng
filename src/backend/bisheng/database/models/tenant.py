"""Tenant and UserTenant ORM models + DAO classes.

Part of F001-multi-tenant-core.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, DateTime, Integer, JSON, String, UniqueConstraint, text
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session


class Tenant(SQLModelSerializable, table=True):
    __tablename__ = 'tenant'

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    tenant_code: str = Field(
        sa_column=Column(String(64), nullable=False, unique=True, comment='Tenant code'),
    )
    tenant_name: str = Field(
        sa_column=Column(String(128), nullable=False, comment='Tenant name'),
    )
    logo: Optional[str] = Field(
        default=None,
        sa_column=Column(String(512), nullable=True, comment='Tenant logo URL'),
    )
    root_dept_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment='Root department ID'),
    )
    status: str = Field(
        default='active',
        sa_column=Column(
            String(16), nullable=False,
            server_default=text("'active'"), index=True,
            comment='Status: active/disabled/archived',
        ),
    )
    contact_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(64), nullable=True, comment='Contact name'),
    )
    contact_phone: Optional[str] = Field(
        default=None,
        sa_column=Column(String(32), nullable=True, comment='Contact phone'),
    )
    contact_email: Optional[str] = Field(
        default=None,
        sa_column=Column(String(128), nullable=True, comment='Contact email'),
    )
    quota_config: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True, comment='Tenant-level resource quota'),
    )
    storage_config: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True, comment='Tenant-level storage config override'),
    )
    create_user: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment='Created by user ID'),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
        ),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
        ),
    )


class UserTenant(SQLModelSerializable, table=True):
    __tablename__ = 'user_tenant'

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    user_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True),
    )
    tenant_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True),
    )
    is_default: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False,
            server_default=text('0'),
            comment='Whether this is the default tenant for the user',
        ),
    )
    status: str = Field(
        default='active',
        sa_column=Column(
            String(16), nullable=False,
            server_default=text("'active'"),
            comment='Status: active/disabled',
        ),
    )
    last_access_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True, comment='Last access time'),
    )
    join_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
        ),
    )

    __table_args__ = (
        UniqueConstraint('user_id', 'tenant_id', name='uk_user_tenant'),
    )


# ---------------------------------------------------------------------------
# DAO: TenantDao
# ---------------------------------------------------------------------------

class TenantDao:

    @classmethod
    def get_by_id(cls, tenant_id: int) -> Optional[Tenant]:
        with get_sync_db_session() as session:
            return session.exec(
                select(Tenant).where(Tenant.id == tenant_id)
            ).first()

    @classmethod
    async def aget_by_id(cls, tenant_id: int) -> Optional[Tenant]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Tenant).where(Tenant.id == tenant_id)
            )
            return result.first()

    @classmethod
    def get_by_code(cls, tenant_code: str) -> Optional[Tenant]:
        with get_sync_db_session() as session:
            return session.exec(
                select(Tenant).where(Tenant.tenant_code == tenant_code)
            ).first()

    @classmethod
    async def aget_by_code(cls, tenant_code: str) -> Optional[Tenant]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(Tenant).where(Tenant.tenant_code == tenant_code)
            )
            return result.first()

    @classmethod
    def create_tenant(cls, tenant: Tenant) -> Tenant:
        with get_sync_db_session() as session:
            session.add(tenant)
            session.commit()
            session.refresh(tenant)
            return tenant

    @classmethod
    async def acreate_tenant(cls, tenant: Tenant) -> Tenant:
        async with get_async_db_session() as session:
            session.add(tenant)
            await session.commit()
            await session.refresh(tenant)
            return tenant


# ---------------------------------------------------------------------------
# DAO: UserTenantDao
# ---------------------------------------------------------------------------

class UserTenantDao:

    @classmethod
    def get_user_tenants(cls, user_id: int) -> List[UserTenant]:
        with get_sync_db_session() as session:
            return session.exec(
                select(UserTenant).where(
                    UserTenant.user_id == user_id,
                    UserTenant.status == 'active',
                )
            ).all()

    @classmethod
    async def aget_user_tenants(cls, user_id: int) -> List[UserTenant]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserTenant).where(
                    UserTenant.user_id == user_id,
                    UserTenant.status == 'active',
                )
            )
            return result.all()

    @classmethod
    def get_user_default_tenant(cls, user_id: int) -> Optional[UserTenant]:
        with get_sync_db_session() as session:
            return session.exec(
                select(UserTenant).where(
                    UserTenant.user_id == user_id,
                    UserTenant.is_default == 1,
                    UserTenant.status == 'active',
                )
            ).first()

    @classmethod
    def add_user_to_tenant(
        cls, user_id: int, tenant_id: int, is_default: int = 0,
    ) -> UserTenant:
        with get_sync_db_session() as session:
            ut = UserTenant(
                user_id=user_id,
                tenant_id=tenant_id,
                is_default=is_default,
            )
            session.add(ut)
            session.commit()
            session.refresh(ut)
            return ut

    @classmethod
    async def aadd_user_to_tenant(
        cls, user_id: int, tenant_id: int, is_default: int = 0,
    ) -> UserTenant:
        async with get_async_db_session() as session:
            ut = UserTenant(
                user_id=user_id,
                tenant_id=tenant_id,
                is_default=is_default,
            )
            session.add(ut)
            await session.commit()
            await session.refresh(ut)
            return ut
