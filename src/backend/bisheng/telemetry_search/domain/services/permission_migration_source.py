"""Dashboard-domain source port for the formal F048 data migration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import UserTenant
from bisheng.permission.migration.f048_source_inventory import (
    PermissionMigrationResourceDTO,
    PermissionMigrationSourcePage,
)
from bisheng.telemetry_search.domain.models.dashboard import (
    Dashboard,
    DashboardType,
)


@dataclass(frozen=True, slots=True)
class DashboardMigrationRow:
    tenant_id: int
    resource_id: str
    status: str
    owner_user_id: int | None
    dashboard_type: str
    source_version: str = "1"


class DashboardMigrationRepositoryPort(Protocol):
    async def aexport_permission_rows(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[DashboardMigrationRow, ...], str | None]: ...


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class SqlDashboardMigrationRepository:
    """Dashboard-owned exporter and one-time tenant attribution repair."""

    def __init__(
        self,
        session_factory: SessionFactory = get_async_db_session,
    ) -> None:
        self._session_factory = session_factory

    async def abackfill_custom_dashboard_tenants(self) -> int:
        """Attribute existing custom dashboards to each owner's active tenant.

        This is business-data migration and is called only by the explicit
        F048 script while services are stopped; Alembic never invokes it.
        """

        with bypass_tenant_filter():
            async with self._session_factory() as session:
                statement = (
                    select(Dashboard, UserTenant.tenant_id)
                    .join(
                        UserTenant,
                        UserTenant.user_id == Dashboard.user_id,
                    )
                    .where(
                        Dashboard.dashboard_type == DashboardType.CUSTOM.value,
                        Dashboard.user_id.is_not(None),
                        UserTenant.status == "active",
                        UserTenant.is_active == 1,
                    )
                    .order_by(Dashboard.id)
                )
                rows = list((await session.execute(statement)).all())
                dashboard_ids = [int(row.id) for row, _ in rows]
                if len(dashboard_ids) != len(set(dashboard_ids)):
                    raise ValueError("dashboard owner has multiple active tenant facts")
                all_custom = list(
                    (
                        await session.execute(
                            select(Dashboard.id).where(Dashboard.dashboard_type == DashboardType.CUSTOM.value)
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(rows) != len(all_custom):
                    raise ValueError("custom dashboard has no unique active owner tenant")
                changed = 0
                async with session.begin_nested():
                    for dashboard, tenant_id in rows:
                        if dashboard.tenant_id == tenant_id:
                            continue
                        await session.execute(
                            update(Dashboard).where(Dashboard.id == dashboard.id).values(tenant_id=int(tenant_id))
                        )
                        changed += 1
                await session.commit()
        return changed

    async def aexport_permission_rows(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[DashboardMigrationRow, ...], str | None]:
        if cursor is not None and not cursor.isdigit():
            raise ValueError("invalid dashboard migration cursor")
        after_id = int(cursor or 0)
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                statement = (
                    select(Dashboard).where(col(Dashboard.id) > after_id).order_by(Dashboard.id).limit(limit + 1)
                )
                raw_rows = list((await session.execute(statement)).scalars().all())
        selected = raw_rows[:limit]
        rows = tuple(
            DashboardMigrationRow(
                tenant_id=int(row.tenant_id or 0),
                resource_id=str(row.id),
                status=str(row.status).upper(),
                owner_user_id=row.user_id,
                dashboard_type=str(row.dashboard_type),
                source_version=(row.update_time.isoformat() if row.update_time is not None else "0"),
            )
            for row in selected
        )
        next_cursor = str(selected[-1].id) if len(raw_rows) > limit and selected else None
        return rows, next_cursor


class DashboardPermissionMigrationSource:
    """Export dashboard tenant/type/owner/status as business facts."""

    def __init__(self, repository: DashboardMigrationRepositoryPort) -> None:
        self._repository = repository

    async def aexport(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> PermissionMigrationSourcePage:
        if not 1 <= limit <= 500:
            raise ValueError("dashboard migration page size must be 1..500")
        rows, next_cursor = await self._repository.aexport_permission_rows(
            cursor=cursor,
            limit=limit,
        )
        items: list[PermissionMigrationResourceDTO] = []
        for row in rows:
            items.append(
                PermissionMigrationResourceDTO(
                    tenant_id=row.tenant_id,
                    resource_type="dashboard",
                    resource_id=row.resource_id,
                    status=row.status,
                    owner_user_id=row.owner_user_id,
                    ownership_kind="USER",
                    source_locator=f"dashboard:{row.resource_id}",
                    system_allowlisted=False,
                    source_version=row.source_version,
                )
            )
        return PermissionMigrationSourcePage(
            items=tuple(items),
            next_cursor=next_cursor,
        )
