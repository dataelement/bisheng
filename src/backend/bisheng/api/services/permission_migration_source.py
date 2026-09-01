"""Application-domain source port for the formal F048 data migration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.assistant import (
    Assistant,
    AssistantStatus,
)
from bisheng.database.models.flow import Flow, FlowStatus, FlowType
from bisheng.permission.migration.f048_source_inventory import (
    PermissionMigrationResourceDTO,
    PermissionMigrationSourcePage,
)


@dataclass(frozen=True, slots=True)
class ApplicationMigrationRow:
    tenant_id: int
    resource_type: str
    resource_id: str
    status: str
    owner_user_id: int | None
    builtin: bool
    system_allowlisted: bool
    source_version: str = "1"


class ApplicationMigrationRepositoryPort(Protocol):
    async def aexport_permission_rows(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[ApplicationMigrationRow, ...], str | None]: ...


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _application_status(enum_type, value: object) -> str:
    try:
        return str(enum_type(value).name)
    except ValueError:
        return f"UNKNOWN:{value}"


class SqlApplicationMigrationRepository:
    """Read-only workflow/assistant exporter owned by the app domain."""

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
    ) -> tuple[tuple[ApplicationMigrationRow, ...], str | None]:
        phase, after_id = self._parse_cursor(cursor)
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                if phase == "workflow":
                    rows, next_cursor = await self._workflow_rows(
                        session,
                        after_id=after_id,
                        limit=limit,
                    )
                    if next_cursor != "assistant:":
                        return tuple(rows), next_cursor
                    assistants, assistant_cursor = await self._assistant_rows(
                        session,
                        after_id="",
                        limit=limit - len(rows),
                    )
                    return (*rows, *assistants), assistant_cursor
                rows, next_cursor = await self._assistant_rows(
                    session,
                    after_id=after_id,
                    limit=limit,
                )
                return tuple(rows), next_cursor

    @staticmethod
    def _parse_cursor(cursor: str | None) -> tuple[str, str]:
        if cursor is None:
            return "workflow", ""
        phase, separator, after_id = cursor.partition(":")
        if not separator or phase not in {"workflow", "assistant"}:
            raise ValueError("invalid application migration cursor")
        return phase, after_id

    async def _workflow_rows(
        self,
        session: AsyncSession,
        *,
        after_id: str,
        limit: int,
    ) -> tuple[list[ApplicationMigrationRow], str | None]:
        if limit <= 0:
            return [], "assistant:"
        statement = (
            select(Flow)
            .where(
                col(Flow.id) > after_id,
                Flow.flow_type == FlowType.WORKFLOW.value,
            )
            .order_by(Flow.id)
            .limit(limit + 1)
        )
        raw_rows = list((await session.execute(statement)).scalars().all())
        selected = raw_rows[:limit]
        rows = [
            ApplicationMigrationRow(
                tenant_id=int(row.tenant_id or 0),
                resource_type="workflow",
                resource_id=str(row.id),
                status=_application_status(FlowStatus, row.status),
                owner_user_id=row.user_id,
                builtin=False,
                system_allowlisted=False,
                source_version=(row.update_time.isoformat() if row.update_time is not None else "0"),
            )
            for row in selected
        ]
        if len(raw_rows) > limit:
            return rows, f"workflow:{selected[-1].id}"
        return rows, "assistant:"

    async def _assistant_rows(
        self,
        session: AsyncSession,
        *,
        after_id: str,
        limit: int,
    ) -> tuple[list[ApplicationMigrationRow], str | None]:
        if limit <= 0:
            return [], "assistant:"
        statement = (
            select(Assistant)
            .where(
                col(Assistant.id) > after_id,
                Assistant.is_delete == 0,
            )
            .order_by(Assistant.id)
            .limit(limit + 1)
        )
        raw_rows = list((await session.execute(statement)).scalars().all())
        selected = raw_rows[:limit]
        rows = [
            ApplicationMigrationRow(
                tenant_id=int(row.tenant_id or 0),
                resource_type="assistant",
                resource_id=str(row.id),
                status=_application_status(AssistantStatus, row.status),
                owner_user_id=row.user_id,
                builtin=False,
                system_allowlisted=False,
                source_version=(row.update_time.isoformat() if row.update_time is not None else "0"),
            )
            for row in selected
        ]
        next_cursor = f"assistant:{selected[-1].id}" if len(raw_rows) > limit and selected else None
        return rows, next_cursor


class ApplicationPermissionMigrationSource:
    """Export workflows and assistants after business predicate validation."""

    def __init__(self, repository: ApplicationMigrationRepositoryPort) -> None:
        self._repository = repository

    async def aexport(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> PermissionMigrationSourcePage:
        if not 1 <= limit <= 500:
            raise ValueError("application migration page size must be 1..500")
        rows, next_cursor = await self._repository.aexport_permission_rows(
            cursor=cursor,
            limit=limit,
        )
        items: list[PermissionMigrationResourceDTO] = []
        for row in rows:
            if row.resource_type not in {"workflow", "assistant"}:
                raise ValueError(f"unsupported application resource: {row.resource_type}")
            system_owned = row.builtin and row.system_allowlisted
            items.append(
                PermissionMigrationResourceDTO(
                    tenant_id=row.tenant_id,
                    resource_type=row.resource_type,
                    resource_id=row.resource_id,
                    status=row.status,
                    owner_user_id=row.owner_user_id,
                    ownership_kind="SYSTEM" if system_owned else "USER",
                    source_locator=(f"application:{row.resource_type}:{row.resource_id}"),
                    system_allowlisted=system_owned,
                    source_version=row.source_version,
                )
            )
        return PermissionMigrationSourcePage(
            items=tuple(items),
            next_cursor=next_cursor,
        )
