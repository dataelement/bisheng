"""Tenant and UserTenant ORM models + DAO classes.

Part of F001-multi-tenant-core.
Extended in F010-tenant-management-ui.
"""

from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import Column, DateTime, Integer, JSON, String, UniqueConstraint, func, text
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.context.tenant import bypass_tenant_filter
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

    @classmethod
    async def alist_tenants(
        cls,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Tenant], int]:
        """Paginated tenant list with optional keyword/status filter.

        Uses bypass_tenant_filter since this is a system admin cross-tenant query.
        """
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                stmt = select(Tenant)
                count_stmt = select(func.count()).select_from(Tenant)

                if keyword:
                    like_pattern = f'%{keyword}%'
                    keyword_filter = Tenant.tenant_name.like(like_pattern) | Tenant.tenant_code.like(like_pattern)
                    stmt = stmt.where(keyword_filter)
                    count_stmt = count_stmt.where(keyword_filter)

                if status:
                    stmt = stmt.where(Tenant.status == status)
                    count_stmt = count_stmt.where(Tenant.status == status)

                result = await session.exec(count_stmt)
                total = result.one()

                stmt = stmt.order_by(Tenant.create_time.desc())
                stmt = stmt.offset((page - 1) * page_size).limit(page_size)
                result = await session.exec(stmt)
                tenants = result.all()

                return list(tenants), total

    @classmethod
    async def aupdate_tenant(cls, tenant_id: int, **fields) -> Optional[Tenant]:
        """Partial update — only updates non-None fields."""
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(
                    select(Tenant).where(Tenant.id == tenant_id)
                )
                tenant = result.first()
                if not tenant:
                    return None
                for key, value in fields.items():
                    if value is not None and hasattr(tenant, key):
                        setattr(tenant, key, value)
                session.add(tenant)
                await session.commit()
                await session.refresh(tenant)
                return tenant

    @classmethod
    async def adelete_tenant(cls, tenant_id: int) -> None:
        """Physically delete a Tenant record."""
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(
                    select(Tenant).where(Tenant.id == tenant_id)
                )
                tenant = result.first()
                if tenant:
                    await session.delete(tenant)
                    await session.commit()

    @classmethod
    async def acount_tenant_users(cls, tenant_id: int) -> int:
        """Count active users in a tenant."""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(func.count()).select_from(UserTenant).where(
                    UserTenant.tenant_id == tenant_id,
                    UserTenant.status == 'active',
                )
            )
            return result.one()

    @classmethod
    async def acount_tenant_users_batch(cls, tenant_ids: List[int]) -> dict:
        """Count active users per tenant in a single query. Returns {tenant_id: count}."""
        if not tenant_ids:
            return {}
        async with get_async_db_session() as session:
            stmt = (
                select(UserTenant.tenant_id, func.count())
                .where(
                    UserTenant.tenant_id.in_(tenant_ids),
                    UserTenant.status == 'active',
                )
                .group_by(UserTenant.tenant_id)
            )
            result = await session.exec(stmt)
            return {row[0]: row[1] for row in result.all()}


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
    async def acreate(cls, user_tenant: UserTenant) -> UserTenant:
        async with get_async_db_session() as session:
            session.add(user_tenant)
            await session.commit()
            await session.refresh(user_tenant)
            return user_tenant

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

    @classmethod
    async def aget_user_tenants_with_details(cls, user_id: int) -> List[dict]:
        """Get user's tenants with tenant details, ordered by last_access_time DESC."""
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                stmt = (
                    select(
                        UserTenant.tenant_id,
                        Tenant.tenant_name,
                        Tenant.tenant_code,
                        Tenant.logo,
                        Tenant.status,
                        UserTenant.last_access_time,
                        UserTenant.is_default,
                    )
                    .join(Tenant, UserTenant.tenant_id == Tenant.id)
                    .where(
                        UserTenant.user_id == user_id,
                        UserTenant.status == 'active',
                    )
                    .order_by(UserTenant.last_access_time.desc())
                )
                result = await session.exec(stmt)
                rows = result.all()
                return [
                    {
                        'tenant_id': row.tenant_id,
                        'tenant_name': row.tenant_name,
                        'tenant_code': row.tenant_code,
                        'logo': row.logo,
                        'status': row.status,
                        'last_access_time': row.last_access_time,
                        'is_default': row.is_default,
                    }
                    for row in rows
                ]

    @classmethod
    async def aremove_user_from_tenant(cls, user_id: int, tenant_id: int) -> None:
        """Physically delete a UserTenant record."""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserTenant).where(
                    UserTenant.user_id == user_id,
                    UserTenant.tenant_id == tenant_id,
                )
            )
            ut = result.first()
            if ut:
                await session.delete(ut)
                await session.commit()

    @classmethod
    async def aupdate_last_access_time(cls, user_id: int, tenant_id: int) -> None:
        """Update last_access_time to now."""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserTenant).where(
                    UserTenant.user_id == user_id,
                    UserTenant.tenant_id == tenant_id,
                )
            )
            ut = result.first()
            if ut:
                ut.last_access_time = datetime.now()
                session.add(ut)
                await session.commit()

    @classmethod
    async def aget_tenant_users(
        cls,
        tenant_id: int,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
    ) -> Tuple[List[dict], int]:
        """Get users in a tenant with pagination. Imports User lazily to avoid circular deps."""
        from bisheng.user.domain.models.user import User

        async with get_async_db_session() as session:
            stmt = (
                select(
                    User.user_id,
                    User.user_name,
                    User.avatar,
                    UserTenant.join_time,
                )
                .join(User, UserTenant.user_id == User.user_id)
                .where(
                    UserTenant.tenant_id == tenant_id,
                    UserTenant.status == 'active',
                )
            )
            count_stmt = (
                select(func.count())
                .select_from(UserTenant)
                .where(
                    UserTenant.tenant_id == tenant_id,
                    UserTenant.status == 'active',
                )
            )

            if keyword:
                like_pattern = f'%{keyword}%'
                stmt = stmt.where(User.user_name.like(like_pattern))
                count_stmt = count_stmt.join(
                    User, UserTenant.user_id == User.user_id
                ).where(User.user_name.like(like_pattern))

            result = await session.exec(count_stmt)
            total = result.one()

            stmt = stmt.order_by(UserTenant.join_time.desc())
            stmt = stmt.offset((page - 1) * page_size).limit(page_size)
            result = await session.exec(stmt)
            rows = result.all()

            return [
                {
                    'user_id': row.user_id,
                    'user_name': row.user_name,
                    'avatar': row.avatar,
                    'join_time': row.join_time,
                }
                for row in rows
            ], total

    @classmethod
    async def aget_user_tenant(cls, user_id: int, tenant_id: int) -> Optional[UserTenant]:
        """Get a single UserTenant record."""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(UserTenant).where(
                    UserTenant.user_id == user_id,
                    UserTenant.tenant_id == tenant_id,
                )
            )
            return result.first()

    @classmethod
    async def adelete_by_tenant(cls, tenant_id: int) -> int:
        """Delete all UserTenant records for a tenant. Returns deleted count."""
        from sqlalchemy import delete as sa_delete
        async with get_async_db_session() as session:
            result = await session.execute(
                sa_delete(UserTenant).where(UserTenant.tenant_id == tenant_id)
            )
            await session.commit()
            return result.rowcount
