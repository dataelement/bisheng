"""SQL repository for the one-time F048 permission data migration."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256

from sqlalchemy import func, insert, or_, update
from sqlmodel import col, select

from bisheng.common.errcode.permission import PermissionVersionConflictError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.permission.domain.models import (
    PermissionMigrationItem,
    PermissionMigrationRun,
)
from bisheng.permission.domain.repositories.catalog_repository import (
    SessionFactory,
    _RepositorySessionMixin,
)
from bisheng.permission.domain.repositories.interfaces import (
    PermissionMigrationRepositoryPort,
)


class MigrationRepository(
    _RepositorySessionMixin,
    PermissionMigrationRepositoryPort,
):
    def __init__(
        self,
        session_factory: SessionFactory = get_async_db_session,
    ) -> None:
        super().__init__(session_factory)

    async def aget_run(
        self,
        run_id: int,
    ) -> PermissionMigrationRun | None:
        async with self._session() as session:
            return await session.get(PermissionMigrationRun, run_id)

    async def aget_or_create_run(
        self,
        run: PermissionMigrationRun,
    ) -> PermissionMigrationRun:
        async with self._session(write=True) as session:
            statement = select(PermissionMigrationRun).where(
                PermissionMigrationRun.environment_fingerprint == run.environment_fingerprint
            )
            existing = (await session.execute(statement)).scalars().first()
            if existing is not None:
                if (
                    existing.store_id != run.store_id
                    or existing.source_model_id != run.source_model_id
                    or (
                        existing.target_model_id is not None
                        and run.target_model_id is not None
                        and existing.target_model_id != run.target_model_id
                    )
                ):
                    raise PermissionVersionConflictError(msg="Migration environment is bound to different model IDs")
                return existing
            session.add(run)
            await session.flush()
            return run

    async def aacquire_environment_lease(
        self,
        *,
        run_id: int,
        expected_version: int,
        lock_token: str,
        expires_at: datetime,
    ) -> bool:
        now = datetime.now(expires_at.tzinfo)
        async with self._session(write=True) as session:
            statement = (
                update(PermissionMigrationRun)
                .where(
                    PermissionMigrationRun.id == run_id,
                    PermissionMigrationRun.version == expected_version,
                    or_(
                        PermissionMigrationRun.lock_expires_at.is_(None),
                        PermissionMigrationRun.lock_expires_at <= now,
                        PermissionMigrationRun.lock_token == lock_token,
                    ),
                )
                .values(
                    lock_token=lock_token,
                    lock_expires_at=expires_at,
                    version=expected_version + 1,
                    update_time=func.now(),
                )
            )
            result = await session.execute(statement)
            return bool(result.rowcount)

    async def aupdate_checkpoint_cas(
        self,
        *,
        run_id: int,
        expected_version: int,
        phase: str,
        checkpoint: str | None,
        source_checksum: str | None,
        target_checksum: str | None,
    ) -> bool:
        async with self._session(write=True) as session:
            statement = (
                update(PermissionMigrationRun)
                .where(
                    PermissionMigrationRun.id == run_id,
                    PermissionMigrationRun.version == expected_version,
                )
                .values(
                    phase=phase,
                    checkpoint=checkpoint,
                    source_checksum=source_checksum,
                    target_checksum=target_checksum,
                    version=expected_version + 1,
                    update_time=func.now(),
                )
            )
            result = await session.execute(statement)
            return bool(result.rowcount)

    async def abind_target_model_cas(
        self,
        *,
        run_id: int,
        expected_version: int,
        target_model_id: str,
    ) -> bool:
        async with self._session(write=True) as session:
            statement = (
                update(PermissionMigrationRun)
                .where(
                    PermissionMigrationRun.id == run_id,
                    PermissionMigrationRun.version == expected_version,
                    or_(
                        PermissionMigrationRun.target_model_id.is_(None),
                        PermissionMigrationRun.target_model_id == target_model_id,
                    ),
                )
                .values(
                    target_model_id=target_model_id,
                    version=expected_version + 1,
                    update_time=func.now(),
                )
            )
            result = await session.execute(statement)
            return bool(result.rowcount)

    async def aupdate_run_state_cas(
        self,
        *,
        run_id: int,
        expected_version: int,
        phase: str,
        status: str,
        checkpoint: str | None,
        source_checksum: str | None,
        target_checksum: str | None,
        report_checksum: str | None = None,
    ) -> bool:
        values: dict[str, object] = {
            "phase": phase,
            "status": status,
            "checkpoint": checkpoint,
            "source_checksum": source_checksum,
            "target_checksum": target_checksum,
            "version": expected_version + 1,
            "update_time": func.now(),
        }
        if report_checksum is not None:
            values["report_checksum"] = report_checksum
        async with self._session(write=True) as session:
            statement = (
                update(PermissionMigrationRun)
                .where(
                    PermissionMigrationRun.id == run_id,
                    PermissionMigrationRun.version == expected_version,
                )
                .values(**values)
            )
            result = await session.execute(statement)
            return bool(result.rowcount)

    async def aupsert_item(
        self,
        item: PermissionMigrationItem,
    ) -> PermissionMigrationItem:
        return (await self.aupsert_items((item,)))[0]

    async def aupsert_items(
        self,
        items: tuple[PermissionMigrationItem, ...],
    ) -> list[PermissionMigrationItem]:
        if not items:
            return []
        if len(items) > 500:
            raise ValueError("migration item batch must not exceed 500")
        keys = {(item.run_id, item.source_kind, item.source_locator) for item in items}
        if len(keys) != len(items):
            raise ValueError("migration item batch contains duplicate keys")
        with bypass_tenant_filter():
            async with self._session(write=True) as session:
                existing_rows: list[PermissionMigrationItem] = []
                for run_id, source_kind in sorted({(item.run_id, item.source_kind) for item in items}):
                    locators = [
                        item.source_locator
                        for item in items
                        if item.run_id == run_id and item.source_kind == source_kind
                    ]
                    statement = select(PermissionMigrationItem).where(
                        PermissionMigrationItem.run_id == run_id,
                        PermissionMigrationItem.source_kind == source_kind,
                        col(PermissionMigrationItem.source_locator).in_(locators),
                    )
                    existing_rows.extend((await session.execute(statement)).scalars().all())
                existing_by_key = {
                    (
                        row.run_id,
                        row.source_kind,
                        row.source_locator,
                    ): row
                    for row in existing_rows
                }
                new_items: list[PermissionMigrationItem] = []
                for item in items:
                    key = (
                        item.run_id,
                        item.source_kind,
                        item.source_locator,
                    )
                    existing = existing_by_key.get(key)
                    if existing is not None:
                        if existing.source_checksum != item.source_checksum:
                            raise PermissionVersionConflictError(msg=("Migration source changed after checkpoint"))
                        continue
                    new_items.append(item)
                if len(items) == 1 and new_items:
                    session.add(new_items[0])
                    await session.flush()
                    return new_items
                if new_items:
                    values = [
                        {
                            column.name: value
                            for column in PermissionMigrationItem.__table__.columns
                            if column.name != "id" and (value := getattr(item, column.name)) is not None
                        }
                        for item in new_items
                    ]
                    await session.execute(
                        insert(PermissionMigrationItem),
                        values,
                    )
                    await session.flush()

                persisted_rows: list[PermissionMigrationItem] = []
                for run_id, source_kind in sorted({(item.run_id, item.source_kind) for item in items}):
                    locators = [
                        item.source_locator
                        for item in items
                        if item.run_id == run_id and item.source_kind == source_kind
                    ]
                    statement = select(PermissionMigrationItem).where(
                        PermissionMigrationItem.run_id == run_id,
                        PermissionMigrationItem.source_kind == source_kind,
                        col(PermissionMigrationItem.source_locator).in_(locators),
                    )
                    persisted_rows.extend((await session.execute(statement)).scalars().all())
                persisted_by_key = {(row.run_id, row.source_kind, row.source_locator): row for row in persisted_rows}
                return [persisted_by_key[(item.run_id, item.source_kind, item.source_locator)] for item in items]

    async def aget_item_cursor(
        self,
        *,
        run_id: int,
        statuses: tuple[str, ...],
        after_id: int,
        limit: int,
    ) -> tuple[list[PermissionMigrationItem], int | None]:
        if limit <= 0 or not statuses:
            return [], None
        with bypass_tenant_filter():
            async with self._session() as session:
                statement = (
                    select(PermissionMigrationItem)
                    .where(
                        PermissionMigrationItem.run_id == run_id,
                        PermissionMigrationItem.status.in_(statuses),
                        PermissionMigrationItem.id > after_id,
                    )
                    .order_by(PermissionMigrationItem.id)
                    .limit(limit + 1)
                )
                rows = list((await session.execute(statement)).scalars().all())
        items = rows[:limit]
        next_cursor = int(items[-1].id) if len(rows) > limit and items else None
        return items, next_cursor

    async def alist_source_items(
        self,
        *,
        run_id: int,
    ) -> list[PermissionMigrationItem]:
        with bypass_tenant_filter():
            async with self._session() as session:
                statement = (
                    select(PermissionMigrationItem)
                    .where(
                        PermissionMigrationItem.run_id == run_id,
                        PermissionMigrationItem.source_kind != "TARGET_TUPLE",
                    )
                    .order_by(
                        PermissionMigrationItem.source_kind,
                        PermissionMigrationItem.source_locator,
                    )
                )
                return list((await session.execute(statement)).scalars().all())

    async def aget_run_checksum(self, run_id: int) -> str | None:
        with bypass_tenant_filter():
            async with self._session() as session:
                run_statement = select(PermissionMigrationRun).where(PermissionMigrationRun.id == run_id)
                run = (await session.execute(run_statement)).scalars().first()
                if run is None:
                    return None
                statement = (
                    select(PermissionMigrationItem)
                    .where(PermissionMigrationItem.run_id == run_id)
                    .order_by(
                        PermissionMigrationItem.source_kind,
                        PermissionMigrationItem.source_locator,
                    )
                )
                items = list((await session.execute(statement)).scalars().all())
        payload = {
            "environment": {
                "store_id": run.store_id,
                "source_model_id": run.source_model_id,
                "source_watermark": run.source_watermark or "",
            },
            "items": [
                {
                    "kind": item.source_kind,
                    "locator": item.source_locator,
                    "checksum": item.source_checksum,
                    "status": item.status,
                    "severity": item.severity,
                    "difference_type": item.difference_type,
                }
                for item in items
                if item.source_kind != "TARGET_TUPLE"
            ],
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return sha256(canonical.encode("utf-8")).hexdigest()
