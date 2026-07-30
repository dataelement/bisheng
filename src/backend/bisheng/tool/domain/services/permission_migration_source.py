"""Tool-domain source port for the formal F048 data migration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.permission.migration.f048_source_inventory import (
    PermissionMigrationResourceDTO,
    PermissionMigrationSourcePage,
)
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.models.gpts_tools import GptsToolsType


@dataclass(frozen=True, slots=True)
class ToolMigrationRow:
    tenant_id: int
    resource_id: str
    status: str
    owner_user_id: int | None
    preset: bool
    system_allowlisted: bool
    source_version: str = "1"


class ToolMigrationRepositoryPort(Protocol):
    async def aexport_permission_rows(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[ToolMigrationRow, ...], str | None]: ...


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class SqlToolMigrationRepository:
    """Read-only tool-category exporter with an explicit system predicate."""

    def __init__(
        self,
        session_factory: SessionFactory = get_async_db_session,
    ) -> None:
        self._session_factory = session_factory

    async def aexport_permission_rows(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[ToolMigrationRow, ...], str | None]:
        if cursor is not None and not cursor.isdigit():
            raise ValueError("invalid tool migration cursor")
        after_id = int(cursor or 0)
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                statement = (
                    select(GptsToolsType)
                    .where(
                        col(GptsToolsType.id) > after_id,
                        GptsToolsType.is_delete == 0,
                    )
                    .order_by(GptsToolsType.id)
                    .limit(limit + 1)
                )
                raw_rows = list((await session.execute(statement)).scalars().all())
        selected = raw_rows[:limit]
        rows = tuple(
            ToolMigrationRow(
                tenant_id=int(row.tenant_id or 0),
                resource_id=str(row.id),
                status="ACTIVE",
                owner_user_id=row.user_id,
                preset=row.is_preset == ToolPresetType.PRESET.value,
                system_allowlisted=(row.is_preset == ToolPresetType.PRESET.value and row.user_id is None),
                source_version=(row.update_time.isoformat() if row.update_time is not None else "0"),
            )
            for row in selected
        )
        next_cursor = str(selected[-1].id) if len(raw_rows) > limit and selected else None
        return rows, next_cursor


class ToolPermissionMigrationSource:
    """Require both preset truth and an explicit code allowlist predicate."""

    def __init__(self, repository: ToolMigrationRepositoryPort) -> None:
        self._repository = repository

    async def aexport(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> PermissionMigrationSourcePage:
        if not 1 <= limit <= 500:
            raise ValueError("tool migration page size must be 1..500")
        rows, next_cursor = await self._repository.aexport_permission_rows(
            cursor=cursor,
            limit=limit,
        )
        items: list[PermissionMigrationResourceDTO] = []
        for row in rows:
            system_owned = row.preset and row.system_allowlisted
            items.append(
                PermissionMigrationResourceDTO(
                    tenant_id=row.tenant_id,
                    resource_type="tool",
                    resource_id=row.resource_id,
                    status=row.status,
                    owner_user_id=row.owner_user_id,
                    ownership_kind="SYSTEM" if system_owned else "USER",
                    source_locator=f"tool:{row.resource_id}",
                    system_allowlisted=system_owned,
                    source_version=row.source_version,
                )
            )
        return PermissionMigrationSourcePage(
            items=tuple(items),
            next_cursor=next_cursor,
        )
