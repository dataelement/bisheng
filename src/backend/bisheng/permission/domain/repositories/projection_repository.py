"""SQL repository for the tenant-scoped projection ledger."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from sqlalchemy import func, update
from sqlmodel import select

from bisheng.common.errcode.permission import PermissionVersionConflictError
from bisheng.core.database import get_async_db_session
from bisheng.permission.domain.models import (
    PermissionProjectionOperation,
    PermissionProjectionTuple,
    PermissionVisibleSourceProjection,
    VisibleSourceProjectionState,
)
from bisheng.permission.domain.repositories.catalog_repository import (
    SessionFactory,
    _RepositorySessionMixin,
)
from bisheng.permission.domain.repositories.interfaces import (
    PermissionProjectionRepositoryPort,
)


class ProjectionRepository(
    _RepositorySessionMixin,
    PermissionProjectionRepositoryPort,
):
    def __init__(
        self,
        session_factory: SessionFactory = get_async_db_session,
    ) -> None:
        super().__init__(session_factory)

    async def aget_operation(
        self,
        operation_id: int,
    ) -> PermissionProjectionOperation | None:
        async with self._session() as session:
            statement = select(PermissionProjectionOperation).where(PermissionProjectionOperation.id == operation_id)
            return (await session.execute(statement)).scalars().first()

    async def aget_operation_by_idempotency(
        self,
        idempotency_key: str,
        *,
        for_update: bool = False,
    ) -> PermissionProjectionOperation | None:
        async with self._session() as session:
            statement = select(PermissionProjectionOperation).where(
                PermissionProjectionOperation.idempotency_key == idempotency_key
            )
            if for_update:
                statement = statement.with_for_update()
            return (await session.execute(statement)).scalars().first()

    async def acreate_operation(
        self,
        operation: PermissionProjectionOperation,
        tuples: list[PermissionProjectionTuple],
    ) -> PermissionProjectionOperation:
        async with self._session(write=True) as session:
            statement = select(PermissionProjectionOperation).where(
                PermissionProjectionOperation.idempotency_key == operation.idempotency_key
            )
            existing = (await session.execute(statement)).scalars().first()
            if existing is not None:
                if existing.request_checksum != operation.request_checksum:
                    raise PermissionVersionConflictError(
                        msg="Idempotency key is bound to a different permission request"
                    )
                return existing

            session.add(operation)
            await session.flush()
            for tuple_row in tuples:
                tuple_row.operation_id = operation.id
                session.add(tuple_row)
            await session.flush()
            return operation

    async def aupdate_operation_status_cas(
        self,
        *,
        operation_id: int,
        expected_status: str,
        target_status: str,
        commit_checksum: str | None = None,
        error_code: int | None = None,
        error_message: str | None = None,
    ) -> bool:
        values: dict[str, object] = {
            "status": target_status,
            "update_time": func.now(),
        }
        if commit_checksum is not None:
            values["commit_checksum"] = commit_checksum
        if error_code is not None:
            values["error_code"] = error_code
        if error_message is not None:
            values["error_message"] = error_message[:4096]

        async with self._session(write=True) as session:
            statement = (
                update(PermissionProjectionOperation)
                .where(
                    PermissionProjectionOperation.id == operation_id,
                    PermissionProjectionOperation.status == expected_status,
                )
                .values(**values)
            )
            result = await session.execute(statement)
            return bool(result.rowcount)

    async def aget_operation_tuples(
        self,
        operation_id: int,
    ) -> list[PermissionProjectionTuple]:
        async with self._session() as session:
            statement = (
                select(PermissionProjectionTuple)
                .where(PermissionProjectionTuple.operation_id == operation_id)
                .order_by(
                    PermissionProjectionTuple.phase,
                    PermissionProjectionTuple.sequence,
                    PermissionProjectionTuple.tuple_fingerprint,
                )
            )
            return list((await session.execute(statement)).scalars().all())

    async def aget_retry_cursor(
        self,
        *,
        statuses: tuple[str, ...],
        updated_before: datetime,
        after_id: int,
        limit: int,
    ) -> tuple[list[PermissionProjectionOperation], int | None]:
        if limit <= 0 or not statuses:
            return [], None
        async with self._session() as session:
            statement = (
                select(PermissionProjectionOperation)
                .where(
                    PermissionProjectionOperation.status.in_(statuses),
                    PermissionProjectionOperation.update_time <= updated_before,
                    PermissionProjectionOperation.id > after_id,
                )
                .order_by(PermissionProjectionOperation.id)
                .limit(limit + 1)
            )
            rows = list((await session.execute(statement)).scalars().all())
        items = rows[:limit]
        next_cursor = int(items[-1].id) if len(rows) > limit and items else None
        return items, next_cursor

    async def aget_operation_checksum(self, operation_id: int) -> str | None:
        tuples = await self.aget_operation_tuples(operation_id)
        if not tuples:
            async with self._session() as session:
                exists_statement = select(func.count(PermissionProjectionOperation.id)).where(
                    PermissionProjectionOperation.id == operation_id
                )
                if int((await session.execute(exists_statement)).scalar_one()) == 0:
                    return None
        canonical = "\n".join(
            "\0".join(
                (
                    row.phase,
                    str(row.sequence),
                    row.action,
                    row.fga_user,
                    row.relation,
                    row.fga_object,
                    row.inverse_action,
                )
            )
            for row in tuples
        )
        return sha256(canonical.encode()).hexdigest()

    async def aupsert_visible_source(
        self,
        source: PermissionVisibleSourceProjection,
    ) -> PermissionVisibleSourceProjection:
        async with self._session(write=True) as session:
            statement = (
                select(PermissionVisibleSourceProjection)
                .where(
                    PermissionVisibleSourceProjection.resource_type == source.resource_type,
                    PermissionVisibleSourceProjection.resource_id == source.resource_id,
                    PermissionVisibleSourceProjection.visibility_class == source.visibility_class,
                    PermissionVisibleSourceProjection.projected_subject == source.projected_subject,
                    PermissionVisibleSourceProjection.contribution_fingerprint
                    == source.contribution_fingerprint,
                )
                .with_for_update()
            )
            existing = (await session.execute(statement)).scalars().first()
            if existing is None:
                session.add(source)
                await session.flush()
                return source

            collision_fields = (
                "source_kind",
                "source_owner_key",
                "source_locator",
                "source_fingerprint",
                "model_key",
            )
            if any(getattr(existing, field) != getattr(source, field) for field in collision_fields):
                raise PermissionVersionConflictError(
                    msg="Visible source contribution fingerprint collision"
                )
            if source.source_version < existing.source_version:
                raise PermissionVersionConflictError(msg="Visible source version is stale")

            mutable_fields = (
                "source_version",
                "tuple_fingerprint",
                "state",
                "operation_id",
                "migration_item_id",
            )
            if source.source_version == existing.source_version:
                if all(getattr(existing, field) == getattr(source, field) for field in mutable_fields):
                    return existing
                raise PermissionVersionConflictError(
                    msg="Visible source version is bound to a different projection"
                )

            for field in mutable_fields:
                setattr(existing, field, getattr(source, field))
            existing.update_time = datetime.now()
            session.add(existing)
            await session.flush()
            return existing

    async def aretire_visible_source(
        self,
        *,
        projection_id: int,
        expected_source_version: int,
        operation_id: int | None,
    ) -> bool:
        async with self._session(write=True) as session:
            statement = (
                select(PermissionVisibleSourceProjection)
                .where(PermissionVisibleSourceProjection.id == projection_id)
                .with_for_update()
            )
            existing = (await session.execute(statement)).scalars().first()
            if existing is None or existing.source_version != expected_source_version:
                return False
            if existing.state == VisibleSourceProjectionState.RETIRED.value:
                return True
            existing.state = VisibleSourceProjectionState.RETIRED.value
            if operation_id is not None:
                existing.operation_id = operation_id
            existing.update_time = datetime.now()
            session.add(existing)
            await session.flush()
            return True

    async def acount_active_visible_sources(
        self,
        *,
        resource_type: str,
        resource_id: str,
        visibility_class: str,
        projected_subject: str,
    ) -> int:
        async with self._session() as session:
            statement = select(func.count(PermissionVisibleSourceProjection.id)).where(
                PermissionVisibleSourceProjection.resource_type == resource_type,
                PermissionVisibleSourceProjection.resource_id == resource_id,
                PermissionVisibleSourceProjection.visibility_class == visibility_class,
                PermissionVisibleSourceProjection.projected_subject == projected_subject,
                PermissionVisibleSourceProjection.state == VisibleSourceProjectionState.ACTIVE.value,
            )
            return int((await session.execute(statement)).scalar_one())

    async def aget_visible_model_cursor(
        self,
        *,
        model_key: str,
        states: tuple[str, ...],
        after_id: int,
        limit: int,
    ) -> tuple[list[PermissionVisibleSourceProjection], int | None]:
        return await self._aget_visible_source_cursor(
            conditions=(PermissionVisibleSourceProjection.model_key == model_key,),
            states=states,
            after_id=after_id,
            limit=limit,
        )

    async def aget_visible_source_cursor(
        self,
        *,
        source_kind: str,
        source_owner_key: str,
        states: tuple[str, ...],
        after_id: int,
        limit: int,
    ) -> tuple[list[PermissionVisibleSourceProjection], int | None]:
        return await self._aget_visible_source_cursor(
            conditions=(
                PermissionVisibleSourceProjection.source_kind == source_kind,
                PermissionVisibleSourceProjection.source_owner_key == source_owner_key,
            ),
            states=states,
            after_id=after_id,
            limit=limit,
        )

    async def aget_visible_migration_cursor(
        self,
        *,
        migration_item_id: int,
        after_id: int,
        limit: int,
    ) -> tuple[list[PermissionVisibleSourceProjection], int | None]:
        return await self._aget_visible_source_cursor(
            conditions=(PermissionVisibleSourceProjection.migration_item_id == migration_item_id,),
            states=(),
            after_id=after_id,
            limit=limit,
            require_states=False,
        )

    async def aget_visible_operation_sources(
        self,
        operation_id: int,
    ) -> list[PermissionVisibleSourceProjection]:
        async with self._session() as session:
            statement = (
                select(PermissionVisibleSourceProjection)
                .where(PermissionVisibleSourceProjection.operation_id == operation_id)
                .order_by(PermissionVisibleSourceProjection.id)
            )
            return list((await session.execute(statement)).scalars().all())

    async def aget_visible_operation_checksum(self, operation_id: int) -> str | None:
        rows = await self.aget_visible_operation_sources(operation_id)
        return _visible_source_checksum(rows)

    async def aget_visible_source_checksum(
        self,
        *,
        states: tuple[str, ...],
        model_key: str | None = None,
    ) -> str | None:
        if not states:
            return None
        async with self._session() as session:
            statement = select(PermissionVisibleSourceProjection).where(
                PermissionVisibleSourceProjection.state.in_(states)
            )
            if model_key is not None:
                statement = statement.where(PermissionVisibleSourceProjection.model_key == model_key)
            rows = list((await session.execute(statement)).scalars().all())
        return _visible_source_checksum(rows)

    async def _aget_visible_source_cursor(
        self,
        *,
        conditions: tuple,
        states: tuple[str, ...],
        after_id: int,
        limit: int,
        require_states: bool = True,
    ) -> tuple[list[PermissionVisibleSourceProjection], int | None]:
        if limit <= 0 or (require_states and not states):
            return [], None
        async with self._session() as session:
            statement = (
                select(PermissionVisibleSourceProjection)
                .where(
                    *conditions,
                    PermissionVisibleSourceProjection.id > after_id,
                )
                .order_by(PermissionVisibleSourceProjection.id)
                .limit(limit + 1)
            )
            if states:
                statement = statement.where(PermissionVisibleSourceProjection.state.in_(states))
            rows = list((await session.execute(statement)).scalars().all())
        items = rows[:limit]
        next_cursor = int(items[-1].id) if len(rows) > limit and items else None
        return items, next_cursor


def _visible_source_checksum(
    rows: list[PermissionVisibleSourceProjection],
) -> str | None:
    if not rows:
        return None
    canonical_rows = sorted(
        "\0".join(
            (
                str(row.tenant_id),
                row.resource_type,
                row.resource_id,
                row.visibility_class,
                row.projected_subject,
                row.source_kind,
                row.source_owner_key,
                row.source_locator,
                row.source_fingerprint,
                row.contribution_fingerprint,
                row.model_key or "",
                str(row.source_version),
                row.tuple_fingerprint,
                row.state,
                str(row.operation_id or ""),
                str(row.migration_item_id or ""),
            )
        )
        for row in rows
    )
    return sha256("\n".join(canonical_rows).encode()).hexdigest()
