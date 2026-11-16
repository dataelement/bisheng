"""SQL repository for global F048 Catalog releases."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import and_, func, or_, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.permission.domain.models import (
    PermissionCatalogRelease,
    PermissionGrant,
)
from bisheng.permission.domain.repositories.interfaces import (
    PermissionCatalogRepositoryPort,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class _RepositorySessionMixin:
    """Small async unit-of-work helper shared by permission repositories."""

    def __init__(
        self,
        session_factory: SessionFactory = get_async_db_session,
    ) -> None:
        self._session_factory = session_factory
        self._active_session: ContextVar[AsyncSession | None] = ContextVar(
            f"permission_repository_session_{id(self)}",
            default=None,
        )

    @asynccontextmanager
    async def bind_session(self, session: AsyncSession) -> AsyncIterator[None]:
        """Borrow an Owner UOW; never commit or close the caller's session."""
        token = self._active_session.set(session)
        try:
            yield
        finally:
            self._active_session.reset(token)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_RepositorySessionMixin]:
        current = self._active_session.get()
        if current is not None:
            yield self
            return

        async with self._session_factory() as session:
            token = self._active_session.set(session)
            try:
                async with session.begin():
                    yield self
            finally:
                self._active_session.reset(token)

    @asynccontextmanager
    async def _session(self, *, write: bool = False) -> AsyncIterator[AsyncSession]:
        current = self._active_session.get()
        if current is not None:
            yield current
            return

        async with self._session_factory() as session:
            if write:
                async with session.begin():
                    yield session
            else:
                yield session


class CatalogRepository(
    _RepositorySessionMixin,
    PermissionCatalogRepositoryPort,
):
    async def aget_recovery_environment(self, *, lock: bool = False) -> dict:
        """Read or lock the exact global release used by an operational recovery."""
        from bisheng.common.errcode.permission import PermissionPublishNotReadyError
        from bisheng.permission.domain.models import AuthorizationModelRelease

        with bypass_tenant_filter():
            async with self._session() as session:
                statement = select(PermissionCatalogRelease).where(PermissionCatalogRelease.status == "CURRENT")
                if lock:
                    statement = statement.with_for_update(nowait=True).execution_options(populate_existing=True)
                rows = list((await session.execute(statement)).scalars().all())
                if len(rows) != 1 or rows[0].write_fenced:
                    raise PermissionPublishNotReadyError(msg="Recovery Catalog is missing, ambiguous or fenced")
                catalog = rows[0]
                statement = select(AuthorizationModelRelease).where(
                    AuthorizationModelRelease.id == catalog.required_authorization_model_release_id,
                )
                if lock:
                    statement = statement.with_for_update(nowait=True).execution_options(populate_existing=True)
                model = (await session.execute(statement)).scalars().first()
                if model is None or model.status != "ACTIVE":
                    raise PermissionPublishNotReadyError(msg="Recovery authorization release is not ACTIVE")
                return {
                    "catalog_id": int(catalog.id),
                    "catalog_version": int(catalog.version),
                    "catalog_checksum": catalog.checksum,
                    "model_release_id": int(model.id),
                    "store_id": model.store_id,
                    "model_id": model.model_id,
                    "model_checksum": model.model_checksum,
                }

    async def aget_current_release(
        self,
        *,
        for_update: bool = False,
    ) -> PermissionCatalogRelease | None:
        async with self._session() as session:
            statement = (
                select(PermissionCatalogRelease)
                .where(PermissionCatalogRelease.status == "CURRENT")
                .order_by(PermissionCatalogRelease.version.desc())
                .limit(1)
            )
            if for_update:
                statement = statement.with_for_update()
            result = await session.execute(statement)
            return result.scalars().first()

    async def aget_release(
        self,
        release_id: int,
    ) -> PermissionCatalogRelease | None:
        async with self._session() as session:
            return await session.get(PermissionCatalogRelease, release_id)

    async def acreate_release(
        self,
        release: PermissionCatalogRelease,
    ) -> PermissionCatalogRelease:
        async with self._session(write=True) as session:
            statement = select(PermissionCatalogRelease).where(
                PermissionCatalogRelease.idempotency_key == release.idempotency_key
            )
            existing = (await session.execute(statement)).scalars().first()
            if existing is not None:
                return existing
            session.add(release)
            await session.flush()
            return release

    async def aupdate_release_cas(
        self,
        *,
        release_id: int,
        expected_version: int,
        values: dict[str, Any],
    ) -> bool:
        async with self._session(write=True) as session:
            statement = (
                update(PermissionCatalogRelease)
                .where(
                    PermissionCatalogRelease.id == release_id,
                    PermissionCatalogRelease.version == expected_version,
                )
                .values(
                    **values,
                    version=expected_version + 1,
                    update_time=func.now(),
                )
            )
            result = await session.execute(statement)
            return bool(result.rowcount)

    async def aget_impact_cursor(
        self,
        *,
        after_tenant_id: int | None,
        after_resource_type: str | None,
        after_resource_id: str | None,
        limit: int,
    ) -> tuple[list[tuple[int, str, str]], tuple[int, str, str] | None]:
        if limit <= 0:
            return [], None

        with bypass_tenant_filter():
            async with self._session() as session:
                statement = (
                    select(
                        PermissionGrant.tenant_id,
                        PermissionGrant.resource_type,
                        PermissionGrant.resource_id,
                    )
                    .where(PermissionGrant.state != "INACTIVE")
                    .distinct()
                    .order_by(
                        PermissionGrant.tenant_id,
                        PermissionGrant.resource_type,
                        PermissionGrant.resource_id,
                    )
                    .limit(limit + 1)
                )
                if after_tenant_id is not None and after_resource_type is not None and after_resource_id is not None:
                    statement = statement.where(
                        or_(
                            PermissionGrant.tenant_id > after_tenant_id,
                            and_(
                                PermissionGrant.tenant_id == after_tenant_id,
                                PermissionGrant.resource_type > after_resource_type,
                            ),
                            and_(
                                PermissionGrant.tenant_id == after_tenant_id,
                                PermissionGrant.resource_type == after_resource_type,
                                PermissionGrant.resource_id > after_resource_id,
                            ),
                        )
                    )
                raw_rows = (await session.execute(statement)).all()

        rows = [(int(row[0]), str(row[1]), str(row[2])) for row in raw_rows[:limit]]
        next_cursor = rows[-1] if len(raw_rows) > limit and rows else None
        return rows, next_cursor

    async def aget_release_checksum(self, release_id: int) -> str | None:
        async with self._session() as session:
            statement = select(PermissionCatalogRelease.checksum).where(PermissionCatalogRelease.id == release_id)
            return (await session.execute(statement)).scalar_one_or_none()
