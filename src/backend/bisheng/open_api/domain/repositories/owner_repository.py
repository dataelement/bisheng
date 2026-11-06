"""Natural-person lookups used by service-account ownership validation."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, func
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import UserTenant
from bisheng.open_api.domain.models.service_account import ServiceAccount
from bisheng.user.domain.models.user import User


@dataclass(frozen=True, slots=True)
class NaturalPersonRecord:
    user_id: int
    user_name: str
    tenant_id: int


@dataclass(frozen=True, slots=True)
class ServiceAccountExecutionBinding:
    account: ServiceAccount
    owner_exists: bool
    owner_tenant_ids: tuple[int, ...]


class OwnerRepository:
    @classmethod
    async def get_unique_management_owner(cls, user_id: int) -> NaturalPersonRecord | None:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                rows = (
                    await session.exec(
                        select(User, UserTenant.tenant_id)
                        .join(UserTenant, UserTenant.user_id == User.user_id)
                        .where(
                            User.user_id == user_id,
                            User.delete == 0,
                            UserTenant.is_active == 1,
                            UserTenant.status == "active",
                        )
                        .limit(2)
                    )
                ).all()
        if len(rows) != 1:
            return None
        user, tenant_id = rows[0]
        return NaturalPersonRecord(user_id=user.user_id, user_name=user.user_name, tenant_id=tenant_id)

    @classmethod
    async def list_management_owners(cls, tenant_id: int, *, keyword: str | None, page: int, page_size: int):
        # Identity membership is global; candidates must have exactly one current relation.
        unique_current = (
            select(func.count())
            .select_from(UserTenant)
            .where(UserTenant.user_id == User.user_id, UserTenant.is_active == 1, UserTenant.status == "active")
            .correlate(User)
            .scalar_subquery()
        )
        filters = [
            User.delete == 0,
            UserTenant.tenant_id == tenant_id,
            UserTenant.is_active == 1,
            UserTenant.status == "active",
            unique_current == 1,
        ]
        if keyword:
            filters.append(User.user_name.like(f"%{keyword}%"))
        size = min(max(page_size, 1), 100)
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                total = (
                    await session.exec(
                        select(func.count())
                        .select_from(User)
                        .join(UserTenant, UserTenant.user_id == User.user_id)
                        .where(*filters)
                    )
                ).one()
                rows = (
                    await session.exec(
                        select(User, UserTenant.tenant_id)
                        .join(UserTenant, UserTenant.user_id == User.user_id)
                        .where(*filters)
                        .order_by(User.user_id)
                        .offset(max(page - 1, 0) * size)
                        .limit(size)
                    )
                ).all()
        return [
            NaturalPersonRecord(user_id=user.user_id, user_name=user.user_name, tenant_id=tid) for user, tid in rows
        ], int(total)

    @classmethod
    async def get_service_account_execution_binding(cls, account_id: int) -> ServiceAccountExecutionBinding | None:
        # Two matches are sufficient to refuse ambiguity; never silently choose one.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                rows = (
                    await session.exec(
                        select(ServiceAccount, User.user_id, UserTenant.tenant_id)
                        .join(User, User.user_id == ServiceAccount.resource_owner_user_id, isouter=True)
                        .join(
                            UserTenant,
                            and_(
                                UserTenant.user_id == User.user_id,
                                UserTenant.is_active == 1,
                                UserTenant.status == "active",
                            ),
                            isouter=True,
                        )
                        .where(ServiceAccount.id == account_id)
                        .limit(2)
                    )
                ).all()
        if not rows:
            return None
        return ServiceAccountExecutionBinding(
            account=rows[0][0],
            owner_exists=rows[0][1] is not None,
            owner_tenant_ids=tuple(int(row[2]) for row in rows if row[2] is not None),
        )

    @classmethod
    async def get_execution_owner_tenant_ids(cls, user_id: int) -> tuple[int, ...]:
        # User.delete is deliberately not an execution-tenancy predicate (F113 AC-08).
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                rows = (
                    await session.exec(
                        select(UserTenant.tenant_id)
                        .join(User, User.user_id == UserTenant.user_id)
                        .where(User.user_id == user_id, UserTenant.is_active == 1, UserTenant.status == "active")
                        .limit(2)
                    )
                ).all()
        return tuple(int(tenant_id) for tenant_id in rows)

    @classmethod
    async def get_user_name(cls, user_id: int | None) -> str | None:
        if user_id is None:
            return None
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                user = (await session.exec(select(User).where(User.user_id == user_id))).first()
        return user.user_name if user else None

    @classmethod
    async def get_active_natural_person(cls, user_id: int) -> NaturalPersonRecord | None:
        return (await cls.get_active_natural_people((user_id,))).get(user_id)

    @classmethod
    async def get_active_natural_people(cls, user_ids: tuple[int, ...]) -> dict[int, NaturalPersonRecord]:
        people = {}
        # Read the actual current tenant even when it differs from the caller's.
        # Callers compare it with the service account's tenant before accepting it.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                # Keep IN clauses bounded for both MySQL and DM8.
                for offset in range(0, len(user_ids), 500):
                    rows = await session.exec(
                        select(User, UserTenant.tenant_id)
                        .join(UserTenant, UserTenant.user_id == User.user_id)
                        .where(
                            User.user_id.in_(user_ids[offset : offset + 500]),
                            User.delete == 0,
                            UserTenant.status == "active",
                            UserTenant.is_active == 1,
                        )
                    )
                    for user, tenant_id in rows.all():
                        people[int(user.user_id)] = NaturalPersonRecord(
                            user_id=int(user.user_id), user_name=user.user_name, tenant_id=int(tenant_id)
                        )
        return people
