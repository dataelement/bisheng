"""SQL repositories for tenant-scoped Grants and permission modes."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, update
from sqlmodel import select

from bisheng.common.errcode.permission import PermissionVersionConflictError
from bisheng.core.database import get_async_db_session
from bisheng.permission.domain.models import (
    PermissionGrant,
    PermissionGrantAssignee,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.catalog_repository import (
    SessionFactory,
    _RepositorySessionMixin,
)
from bisheng.permission.domain.repositories.interfaces import (
    PermissionGrantRepositoryPort,
    ResourcePermissionModeRepositoryPort,
)


class GrantRepository(
    _RepositorySessionMixin,
    PermissionGrantRepositoryPort,
):
    def __init__(
        self,
        session_factory: SessionFactory = get_async_db_session,
    ) -> None:
        super().__init__(session_factory)

    async def aget_grant(
        self,
        *,
        resource_type: str,
        resource_id: str,
        model_key: str,
        for_update: bool = False,
    ) -> PermissionGrant | None:
        async with self._session() as session:
            statement = select(PermissionGrant).where(
                PermissionGrant.resource_type == resource_type,
                PermissionGrant.resource_id == resource_id,
                PermissionGrant.model_key == model_key,
            )
            if for_update:
                statement = statement.with_for_update()
            return (await session.execute(statement)).scalars().first()

    async def acreate_grant(self, grant: PermissionGrant) -> PermissionGrant:
        existing = await self.aget_grant(
            resource_type=grant.resource_type,
            resource_id=grant.resource_id,
            model_key=grant.model_key,
            for_update=True,
        )
        if existing is not None:
            return existing
        async with self._session(write=True) as session:
            session.add(grant)
            await session.flush()
            return grant

    async def aupdate_grant_cas(
        self,
        *,
        grant_id: int,
        expected_version: int,
        values: dict[str, Any],
    ) -> bool:
        async with self._session(write=True) as session:
            statement = (
                update(PermissionGrant)
                .where(
                    PermissionGrant.id == grant_id,
                    PermissionGrant.version == expected_version,
                )
                .values(
                    **values,
                    version=expected_version + 1,
                    update_time=func.now(),
                )
            )
            result = await session.execute(statement)
            return bool(result.rowcount)

    async def aget_assignee(
        self,
        assignee_id: int,
        *,
        for_update: bool = False,
    ) -> PermissionGrantAssignee | None:
        async with self._session() as session:
            statement = select(PermissionGrantAssignee).where(PermissionGrantAssignee.id == assignee_id)
            if for_update:
                statement = statement.with_for_update()
            return (await session.execute(statement)).scalars().first()

    async def acreate_assignee(
        self,
        assignee: PermissionGrantAssignee,
    ) -> PermissionGrantAssignee:
        async with self._session(write=True) as session:
            statement = select(PermissionGrantAssignee).where(
                PermissionGrantAssignee.grant_id == assignee.grant_id,
                PermissionGrantAssignee.source_fingerprint == assignee.source_fingerprint,
            )
            existing = (await session.execute(statement)).scalars().first()
            if existing is not None:
                if (
                    existing.source_locator != assignee.source_locator
                    or existing.subject_type != assignee.subject_type
                    or existing.subject_id != assignee.subject_id
                ):
                    raise PermissionVersionConflictError(msg="Permission assignment source fingerprint collision")
                return existing
            session.add(assignee)
            await session.flush()
            return assignee

    async def aupdate_assignee_cas(
        self,
        *,
        assignee_id: int,
        expected_version: int,
        values: dict[str, Any],
    ) -> bool:
        async with self._session(write=True) as session:
            statement = (
                update(PermissionGrantAssignee)
                .where(
                    PermissionGrantAssignee.id == assignee_id,
                    PermissionGrantAssignee.version == expected_version,
                )
                .values(
                    **values,
                    version=expected_version + 1,
                    update_time=func.now(),
                )
            )
            result = await session.execute(statement)
            return bool(result.rowcount)

    async def aget_assignee_cursor(
        self,
        *,
        resource_type: str,
        resource_id: str,
        after_id: int,
        limit: int,
    ) -> tuple[list[PermissionGrantAssignee], int | None]:
        if limit <= 0:
            return [], None
        async with self._session() as session:
            statement = (
                select(PermissionGrantAssignee)
                .join(
                    PermissionGrant,
                    PermissionGrant.id == PermissionGrantAssignee.grant_id,
                )
                .where(
                    PermissionGrant.resource_type == resource_type,
                    PermissionGrant.resource_id == resource_id,
                    PermissionGrantAssignee.id > after_id,
                )
                .order_by(PermissionGrantAssignee.id)
                .limit(limit + 1)
            )
            rows = list((await session.execute(statement)).scalars().all())
        items = rows[:limit]
        next_cursor = int(items[-1].id) if len(rows) > limit and items else None
        return items, next_cursor

    async def acount_projected_subject_sources(
        self,
        *,
        grant_id: int,
        projected_subject: str,
        protected: bool,
    ) -> int:
        async with self._session() as session:
            statement = (
                select(func.count())
                .select_from(PermissionGrantAssignee)
                .where(
                    PermissionGrantAssignee.grant_id == grant_id,
                    PermissionGrantAssignee.projected_subject == projected_subject,
                    PermissionGrantAssignee.protected == protected,
                    PermissionGrantAssignee.state == "ACTIVE",
                )
            )
            return int((await session.execute(statement)).scalar_one())


class ResourcePermissionModeRepository(
    _RepositorySessionMixin,
    ResourcePermissionModeRepositoryPort,
):
    def __init__(
        self,
        session_factory: SessionFactory = get_async_db_session,
    ) -> None:
        super().__init__(session_factory)

    async def aget_mode(
        self,
        *,
        resource_type: str,
        resource_id: str,
        for_update: bool = False,
    ) -> ResourcePermissionMode | None:
        async with self._session() as session:
            statement = select(ResourcePermissionMode).where(
                ResourcePermissionMode.resource_type == resource_type,
                ResourcePermissionMode.resource_id == resource_id,
            )
            if for_update:
                statement = statement.with_for_update()
            return (await session.execute(statement)).scalars().first()

    async def acreate_mode(
        self,
        mode: ResourcePermissionMode,
    ) -> ResourcePermissionMode:
        existing = await self.aget_mode(
            resource_type=mode.resource_type,
            resource_id=mode.resource_id,
            for_update=True,
        )
        if existing is not None:
            return existing
        async with self._session(write=True) as session:
            session.add(mode)
            await session.flush()
            return mode

    async def aupdate_mode_cas(
        self,
        *,
        mode_id: int,
        expected_version: int,
        values: dict[str, Any],
    ) -> bool:
        async with self._session(write=True) as session:
            statement = (
                update(ResourcePermissionMode)
                .where(
                    ResourcePermissionMode.id == mode_id,
                    ResourcePermissionMode.version == expected_version,
                )
                .values(
                    **values,
                    version=expected_version + 1,
                    update_time=func.now(),
                )
            )
            result = await session.execute(statement)
            return bool(result.rowcount)
