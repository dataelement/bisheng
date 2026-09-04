"""Database operations for independent service-account subjects."""

from __future__ import annotations

from sqlalchemy import func
from sqlmodel import col, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.open_api.domain.models.service_account import ServiceAccount


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
        statement = select(ServiceAccount).where(col(ServiceAccount.deleted_at).is_(None))
        if keyword:
            statement = statement.where(col(ServiceAccount.name).like(f"%{keyword}%"))
        count_statement = select(func.count()).select_from(statement.subquery())
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
