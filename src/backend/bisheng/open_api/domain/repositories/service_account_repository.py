"""Database operations for independent service-account subjects."""

from __future__ import annotations

from sqlalchemy import func
from sqlmodel import col, select

from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    is_tenant_filter_bypassed,
)
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.open_api.domain.models.service_account import ServiceAccount


def current_tenant_scope() -> int | None:
    """Return the tenant every service-account read must be pinned to.

    ``service_account`` is tenant-aware, so the global filter already narrows
    these reads — but for a child-tenant caller it injects the F012 IN-list
    ``tenant_id IN (leaf, ROOT)``, which shares Root rows downwards. Service
    accounts are tenant-private: a child-tenant administrator must never list,
    read or mutate a Root account, let alone issue keys against it. So every
    management read carries its own equality predicate on top of the IN-list.

    ``None`` means "add no predicate": either tenant filtering is deliberately
    bypassed (the execution path reads a credential's own account), or there is
    no tenant context at all (bearer validation runs before one is installed
    and compares ``tenant_id`` against the credential itself).
    """

    if is_tenant_filter_bypassed():
        return None
    return get_current_tenant_id()


class ServiceAccountRepository:
    @classmethod
    async def create(cls, row: ServiceAccount) -> ServiceAccount:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    @classmethod
    async def get(cls, service_account_id: int, *, include_deleted: bool = False) -> ServiceAccount | None:
        statement = select(ServiceAccount).where(ServiceAccount.id == service_account_id)
        if not include_deleted:
            statement = statement.where(col(ServiceAccount.deleted_at).is_(None))
        tenant_id = current_tenant_scope()
        if tenant_id is not None:
            statement = statement.where(ServiceAccount.tenant_id == tenant_id)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).first()

    @classmethod
    async def get_by_ids(cls, service_account_ids: list[int]) -> list[ServiceAccount]:
        if not service_account_ids:
            return []
        statement = select(ServiceAccount).where(
            col(ServiceAccount.id).in_(service_account_ids),
            col(ServiceAccount.deleted_at).is_(None),
        )
        tenant_id = current_tenant_scope()
        if tenant_id is not None:
            statement = statement.where(ServiceAccount.tenant_id == tenant_id)
        async with get_async_db_session() as session:
            return list((await session.exec(statement)).all())

    @classmethod
    def get_for_execution_sync(cls, service_account_id: int) -> ServiceAccount | None:
        with bypass_tenant_filter():
            with get_sync_db_session() as session:
                return session.exec(select(ServiceAccount).where(ServiceAccount.id == service_account_id)).first()

    @classmethod
    async def list_page(
        cls,
        *,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ServiceAccount], int]:
        filters = [col(ServiceAccount.deleted_at).is_(None)]
        tenant_id = current_tenant_scope()
        if tenant_id is not None:
            filters.append(ServiceAccount.tenant_id == tenant_id)
        if keyword:
            filters.append(col(ServiceAccount.name).like(f"%{keyword}%"))
        statement = select(ServiceAccount).where(*filters)
        # Counting over ``statement.subquery()`` hides ``service_account`` from
        # the tenant-filter listener, which only sees the outer froms: ``data``
        # came back filtered while ``total`` stayed a cross-tenant count, and the
        # paginator then offered pages that render empty. Count the same table
        # under the same filters instead.
        count_statement = select(func.count()).select_from(ServiceAccount).where(*filters)
        async with get_async_db_session() as session:
            total = int((await session.exec(count_statement)).one())
            rows = (
                await session.exec(
                    statement.order_by(col(ServiceAccount.create_time).desc(), col(ServiceAccount.id).desc())
                    .offset(max(page - 1, 0) * page_size)
                    .limit(page_size)
                )
            ).all()
        return list(rows), total

    @classmethod
    async def save(cls, row: ServiceAccount) -> ServiceAccount:
        from datetime import datetime

        row.update_time = datetime.now()
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row
