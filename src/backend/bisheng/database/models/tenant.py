"""Tenant and UserTenant ORM models + DAO classes.

Part of F001-multi-tenant-core.
Extended in F010-tenant-management-ui.
"""

import logging
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import (
    Column, DateTime, Integer, JSON, String, UniqueConstraint,
    bindparam, func, text,
)
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session, get_sync_db_session

logger = logging.getLogger(__name__)

# v2.5.1 F011 tenant tree: canonical Root tenant id.
ROOT_TENANT_ID: int = 1


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
            comment='Status: active/disabled/archived/orphaned (orphaned added in v2.5.1 F011)',
        ),
    )
    # v2.5.1 F011: tenant tree fields (2-layer MVP — Root + 0~N Child).
    parent_tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, nullable=True, index=True,
            comment='NULL=Root tenant; else points to Root id (MVP locks to 2 layers)',
        ),
    )
    share_default_to_children: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False, server_default=text('1'),
            comment='1=Root-created resources default to shared_to all children (v2.5.1 F011)',
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
    # v2.5.1 F011: unique-leaf semantic.
    # is_active=1 marks the current leaf tenant; NULL marks history.
    # MySQL UNIQUE allows multiple NULLs, so uk_user_active constrains at
    # most one is_active=1 row per user without forbidding history rows.
    is_active: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, nullable=True,
            comment='1=active leaf (unique per user); NULL=historical record',
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

    # v2.5.1 F011: replaced uk_user_tenant(user_id, tenant_id) with
    # uk_user_active(user_id, is_active). The Alembic migration DROPs the
    # old index and ADDs the new one; the ORM layer only reflects the new
    # unique contract.
    __table_args__ = (
        UniqueConstraint('user_id', 'is_active', name='uk_user_active'),
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

    # -----------------------------------------------------------------------
    # v2.5.1 F011: tenant tree DAO methods (spec §5.4.3).
    # Callers: F016 (Root usage aggregation), F019 (admin_scope cleanup).
    # -----------------------------------------------------------------------

    @classmethod
    async def aget_children_ids_active(cls, root_id: int = ROOT_TENANT_ID) -> List[int]:
        """Return ids of active Child tenants whose parent == root_id.

        Used by F016 Root usage aggregation (INV-T9): only active children
        count toward Root quota. MVP keeps root_id parameterized for 3+ layer
        compatibility but in practice root_id is always 1.
        """
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                stmt = select(Tenant.id).where(
                    Tenant.parent_tenant_id == root_id,
                    Tenant.status == 'active',
                )
                result = await session.exec(stmt)
                return [row for row in result.all()]

    @classmethod
    async def aget_non_active_ids(cls) -> List[int]:
        """Return ids of tenants in disabled/archived/orphaned status.

        Used by F019 Celery sweep to clear admin_scope Redis keys pointing
        at tenants that are no longer reachable.
        """
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                stmt = select(Tenant.id).where(
                    Tenant.status.in_(['disabled', 'archived', 'orphaned'])
                )
                result = await session.exec(stmt)
                return [row for row in result.all()]

    @classmethod
    async def aexists(cls, tenant_id: int) -> bool:
        """Return whether a tenant with this id exists in any status.

        Used by F019 TenantScopeService.set_scope to validate body.tenant_id
        before writing the Redis key (AC-15 → 400 + 19702 if missing).
        """
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                stmt = select(func.count()).select_from(Tenant).where(
                    Tenant.id == tenant_id,
                )
                result = await session.exec(stmt)
                return result.one() > 0

    @classmethod
    async def aget_by_parent(cls, parent_id: Optional[int]) -> List['Tenant']:
        """Return tenants whose parent_tenant_id == parent_id (any status).

        Used by F011 mount conflict checks and admin dashboards. Passing
        None returns Root tenants (MVP: at most one row with id=1).
        """
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                if parent_id is None:
                    stmt = select(Tenant).where(Tenant.parent_tenant_id.is_(None))
                else:
                    stmt = select(Tenant).where(Tenant.parent_tenant_id == parent_id)
                result = await session.exec(stmt)
                return list(result.all())

    # -----------------------------------------------------------------------
    # Cross-table tenant_id rewrite helpers (F011 unmount + migrate-from-root).
    # Kept at the DAO layer so services do not execute raw SQL — even when
    # iterating over a large list of tables maintained as a constant.
    # -----------------------------------------------------------------------

    @classmethod
    async def abulk_update_tenant_id(
        cls,
        tables: List[str],
        from_tenant_id: int,
        to_tenant_id: int,
    ) -> dict:
        """For each ``table``, run ``UPDATE SET tenant_id=<to> WHERE tenant_id=<from>``.

        **Atomic** — any single-table failure aborts the whole batch. The
        session rolls back and the exception propagates to the caller,
        so F011 AC-04a ("事务保证一致性") holds. If a deploy is missing
        one of the whitelisted tables, the caller is expected to prune
        the table list beforehand rather than rely on silent-skip.

        Caller supplies the whitelist — SQL injection is not a concern
        because the names come from application constants, never from
        user input.

        Returns ``{table_name: rowcount}`` on success.
        """
        counts: dict = {}
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                try:
                    for table in tables:
                        res = await session.execute(
                            text(
                                f'UPDATE {table} SET tenant_id = :to_tid '
                                f'WHERE tenant_id = :from_tid'
                            ),
                            {'to_tid': to_tenant_id, 'from_tid': from_tenant_id},
                        )
                        counts[table] = getattr(res, 'rowcount', 0) or 0
                    await session.commit()
                except Exception:
                    # AC-04a atomicity: partial updates must not persist.
                    # Explicit rollback before re-raising — the async context
                    # manager also rolls back but doing it here makes the
                    # intent unmistakable for callers who patch the session.
                    await session.rollback()
                    logger.error(
                        'abulk_update_tenant_id aborted; '
                        'rolling back %d partially-updated tables',
                        len(counts),
                    )
                    raise
        return counts

    @classmethod
    async def afetch_resource_tenant_ids(
        cls, table: str, resource_ids: List[int],
    ) -> dict:
        """Return ``{id: tenant_id}`` for rows in ``table`` with id in list."""
        if not resource_ids:
            return {}
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                stmt = text(
                    f'SELECT id, tenant_id FROM {table} WHERE id IN :ids'
                ).bindparams(bindparam('ids', expanding=True))
                res = await session.execute(stmt, {'ids': resource_ids})
                return {row[0]: row[1] for row in res.all()}

    @classmethod
    async def aupdate_resource_tenant_ids(
        cls, table: str, resource_ids: List[int], new_tenant_id: int,
    ) -> None:
        """Bulk set ``tenant_id = :new`` for rows in ``table`` with id in list."""
        if not resource_ids:
            return
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                stmt = text(
                    f'UPDATE {table} SET tenant_id = :tid WHERE id IN :ids'
                ).bindparams(bindparam('ids', expanding=True))
                await session.execute(
                    stmt, {'tid': new_tenant_id, 'ids': resource_ids},
                )
                await session.commit()


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

    # -----------------------------------------------------------------------
    # v2.5.1 F011: unique-leaf operations.
    # Callers: F012 TenantResolver (deactivate on primary-department relocate,
    # activate new leaf), F013 permission checks (resolve current leaf).
    # -----------------------------------------------------------------------

    @classmethod
    async def aget_active_user_tenant(cls, user_id: int) -> Optional[UserTenant]:
        """Return the user's current active leaf UserTenant, or None."""
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(
                    select(UserTenant).where(
                        UserTenant.user_id == user_id,
                        UserTenant.is_active == 1,
                    )
                )
                return result.first()

    @classmethod
    async def adeactivate_user_tenant(
        cls, user_id: int, tenant_id: int,
    ) -> int:
        """Set is_active=NULL for a specific (user_id, tenant_id) pair.

        Returns the number of rows affected. Used when a user's primary
        department changes — the old leaf is demoted to history and a new
        active row is created/promoted by ``aactivate_user_tenant``.
        """
        from sqlalchemy import update as sa_update
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.execute(
                    sa_update(UserTenant)
                    .where(
                        UserTenant.user_id == user_id,
                        UserTenant.tenant_id == tenant_id,
                        UserTenant.is_active == 1,
                    )
                    .values(is_active=None)
                )
                await session.commit()
                return result.rowcount

    @classmethod
    async def aactivate_user_tenant(
        cls, user_id: int, tenant_id: int,
    ) -> UserTenant:
        """Promote (user_id, tenant_id) to is_active=1 atomically.

        Steps (single transaction):
          1. Demote the user's current active row (any tenant) to NULL.
          2. UPSERT target row with is_active=1.

        Returns the activated UserTenant row.
        """
        from sqlalchemy import update as sa_update
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                # 1. Demote any existing active row for this user.
                await session.execute(
                    sa_update(UserTenant)
                    .where(
                        UserTenant.user_id == user_id,
                        UserTenant.is_active == 1,
                    )
                    .values(is_active=None)
                )
                # 2. If a history row exists for target (user_id, tenant_id),
                #    promote it; otherwise insert a new one.
                existing = (await session.exec(
                    select(UserTenant).where(
                        UserTenant.user_id == user_id,
                        UserTenant.tenant_id == tenant_id,
                    )
                )).first()
                if existing is not None:
                    existing.is_active = 1
                    existing.status = 'active'
                    session.add(existing)
                    await session.commit()
                    await session.refresh(existing)
                    return existing
                new_row = UserTenant(
                    user_id=user_id, tenant_id=tenant_id,
                    is_active=1, is_default=1, status='active',
                )
                session.add(new_row)
                await session.commit()
                await session.refresh(new_row)
                return new_row
