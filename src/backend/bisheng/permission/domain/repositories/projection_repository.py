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
