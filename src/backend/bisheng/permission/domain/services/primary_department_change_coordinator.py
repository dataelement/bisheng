from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.permission.domain.repositories.implementations.department_transfer_permission_cleanup_repository_impl import (
    DepartmentTransferPermissionCleanupRepositoryImpl,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedDepartmentChange:
    event_id: int
    user_id: int
    old_department_id: int
    new_department_id: int
    trigger_source: str
    event_key: str


class PrimaryDepartmentChangeCoordinator:
    def __init__(
        self,
        *,
        repository,
        snapshot_service=None,
        dispatcher: Callable[[int], Awaitable[None]] | None = None,
        commit_callback: Callable[[], Awaitable[None]] | None = None,
        tenant_id: int = DEFAULT_TENANT_ID,
    ):
        self.repository = repository
        self.snapshot_service = snapshot_service
        self.dispatcher = dispatcher or _dispatch_cleanup_event
        self.commit_callback = commit_callback
        self.tenant_id = tenant_id

    async def prepare_change(
        self,
        *,
        user_id: int,
        old_department_id: int | None,
        new_department_id: int,
        trigger_source: str,
        source_event_key: str | None,
    ) -> PreparedDepartmentChange | None:
        if old_department_id is None or int(old_department_id) == int(new_department_id):
            return None
        requested_at = datetime.now()
        event = None
        if source_event_key is None and hasattr(
            self.repository,
            "find_active_matching_event",
        ):
            event = await self.repository.find_active_matching_event(
                tenant_id=self.tenant_id,
                user_id=int(user_id),
                old_department_id=int(old_department_id),
                new_department_id=int(new_department_id),
                trigger_source=trigger_source,
            )
        if event is None:
            event_key = self._build_event_key(
                user_id=user_id,
                old_department_id=int(old_department_id),
                new_department_id=int(new_department_id),
                trigger_source=trigger_source,
                source_event_key=source_event_key,
            )
            event = await self.repository.create_or_get_event(
                tenant_id=self.tenant_id,
                event_key=event_key,
                user_id=int(user_id),
                old_department_id=int(old_department_id),
                new_department_id=int(new_department_id),
                trigger_source=trigger_source,
                requested_at=requested_at,
            )
        else:
            event_key = str(event.event_key)
        prepared = PreparedDepartmentChange(
            event_id=int(event.id),
            user_id=int(user_id),
            old_department_id=int(old_department_id),
            new_department_id=int(new_department_id),
            trigger_source=trigger_source,
            event_key=event_key,
        )
        if self.snapshot_service is not None:
            try:
                await self.snapshot_service.capture(event)
            except Exception as exc:
                logger.warning(
                    "department transfer snapshot failed event_id=%s user_id=%s source=%s error_summary=%s",
                    prepared.event_id,
                    prepared.user_id,
                    prepared.trigger_source,
                    f"{type(exc).__name__}:operation_failed",
                )
                if hasattr(self.repository, "set_snapshot_complete"):
                    await self.repository.set_snapshot_complete(
                        prepared.event_id,
                        complete=False,
                        error=f"snapshot_failed:{type(exc).__name__}",
                    )
        return prepared

    async def activate_change(
        self,
        prepared: PreparedDepartmentChange,
        *,
        changed_at: datetime,
    ) -> None:
        await self.repository.activate_event(
            prepared.event_id,
            changed_at=changed_at,
            deadline_at=changed_at + timedelta(minutes=5),
        )
        if self.commit_callback is not None:
            await self.commit_callback()
        try:
            await self.dispatcher(prepared.event_id)
        except Exception as exc:
            logger.warning(
                "department transfer cleanup dispatch failed event_id=%s user_id=%s "
                "old_department_id=%s new_department_id=%s source=%s error_summary=%s",
                prepared.event_id,
                prepared.user_id,
                prepared.old_department_id,
                prepared.new_department_id,
                prepared.trigger_source,
                f"{type(exc).__name__}:operation_failed",
            )

    async def cancel_change(
        self,
        prepared: PreparedDepartmentChange,
        *,
        reason: str,
    ) -> None:
        await self.repository.cancel_event(prepared.event_id, reason=reason)
        if self.commit_callback is not None:
            await self.commit_callback()

    @staticmethod
    def _build_event_key(
        *,
        user_id: int,
        old_department_id: int,
        new_department_id: int,
        trigger_source: str,
        source_event_key: str | None,
    ) -> str:
        source_key = source_event_key or datetime.now().strftime("%Y%m%d%H%M%S%f")
        raw = f"{trigger_source}:{user_id}:{old_department_id}:{new_department_id}:{source_key}"
        if len(raw) <= 128:
            return raw
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"{trigger_source}:{user_id}:{old_department_id}:{new_department_id}:{digest}"[:128]


async def prepare_primary_department_change(
    *,
    user_id: int,
    old_department_id: int | None,
    new_department_id: int,
    trigger_source: str,
    source_event_key: str | None = None,
) -> PreparedDepartmentChange | None:
    """创建调岗事件; 异常只告警, 不回滚调用方的部门业务。"""
    if old_department_id is None or int(old_department_id) == int(new_department_id):
        return None
    try:
        from bisheng.permission.domain.services.department_transfer_grant_guard import (
            DepartmentTransferGrantRetryableError,
            _DepartmentTransferUserLock,
        )
        from bisheng.permission.domain.services.department_transfer_permission_snapshot_service import (
            DepartmentTransferPermissionSnapshotService,
        )

        async def _prepare_and_persist() -> PreparedDepartmentChange | None:
            async with get_async_db_session() as session:
                repository = DepartmentTransferPermissionCleanupRepositoryImpl(session)
                coordinator = PrimaryDepartmentChangeCoordinator(
                    repository=repository,
                    snapshot_service=DepartmentTransferPermissionSnapshotService(
                        session=session,
                        repository=repository,
                    ),
                    tenant_id=get_current_tenant_id() or DEFAULT_TENANT_ID,
                )
                prepared = await coordinator.prepare_change(
                    user_id=user_id,
                    old_department_id=old_department_id,
                    new_department_id=new_department_id,
                    trigger_source=trigger_source,
                    source_event_key=source_event_key,
                )
                await session.commit()
                return prepared

        try:
            async with _DepartmentTransferUserLock(user_id):
                return await _prepare_and_persist()
        except DepartmentTransferGrantRetryableError as exc:
            logger.warning(
                "department transfer prepare lock unavailable; persisting retryable event "
                "user_id=%s old_department_id=%s new_department_id=%s source=%s "
                "error_summary=%s",
                user_id,
                old_department_id,
                new_department_id,
                trigger_source,
                f"{type(exc).__name__}:operation_failed",
            )
            return await _prepare_and_persist()
    except Exception as exc:
        logger.warning(
            "department transfer cleanup prepare failed user_id=%s old_department_id=%s "
            "new_department_id=%s source=%s error_summary=%s",
            user_id,
            old_department_id,
            new_department_id,
            trigger_source,
            f"{type(exc).__name__}:operation_failed",
        )
        return None


async def activate_primary_department_change(
    prepared: PreparedDepartmentChange | None,
    *,
    changed_at: datetime | None = None,
) -> None:
    if prepared is None:
        return
    try:
        async with get_async_db_session() as session:
            coordinator = PrimaryDepartmentChangeCoordinator(
                repository=DepartmentTransferPermissionCleanupRepositoryImpl(session),
                commit_callback=session.commit,
            )
            await coordinator.activate_change(prepared, changed_at=changed_at or datetime.now())
    except Exception as exc:
        logger.warning(
            "department transfer cleanup activate failed event_id=%s user_id=%s "
            "old_department_id=%s new_department_id=%s source=%s error_summary=%s",
            prepared.event_id,
            prepared.user_id,
            prepared.old_department_id,
            prepared.new_department_id,
            prepared.trigger_source,
            f"{type(exc).__name__}:operation_failed",
        )


async def cancel_primary_department_change(
    prepared: PreparedDepartmentChange | None,
    *,
    reason: str,
) -> None:
    if prepared is None:
        return
    try:
        async with get_async_db_session() as session:
            coordinator = PrimaryDepartmentChangeCoordinator(
                repository=DepartmentTransferPermissionCleanupRepositoryImpl(session),
                commit_callback=session.commit,
            )
            await coordinator.cancel_change(prepared, reason=reason)
    except Exception as exc:
        logger.warning(
            "department transfer cleanup cancel failed event_id=%s user_id=%s "
            "old_department_id=%s new_department_id=%s source=%s error_summary=%s",
            prepared.event_id,
            prepared.user_id,
            prepared.old_department_id,
            prepared.new_department_id,
            prepared.trigger_source,
            f"{type(exc).__name__}:operation_failed",
        )


async def _dispatch_cleanup_event(event_id: int) -> None:
    from bisheng.worker.permission.department_transfer_cleanup import process_event

    process_event.apply_async(args=[event_id], queue="knowledge_celery")
