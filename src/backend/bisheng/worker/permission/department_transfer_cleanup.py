from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlmodel import select

from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import UserDepartment
from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
    DepartmentTransferCleanupEventStatus,
)
from bisheng.permission.domain.repositories.implementations.department_transfer_permission_cleanup_repository_impl import (
    DepartmentTransferPermissionCleanupRepositoryImpl,
)
from bisheng.permission.domain.services.department_transfer_permission_cleanup_service import (
    DepartmentTransferPermissionCleanupService,
)
from bisheng.permission.domain.services.department_transfer_permission_snapshot_service import (
    DepartmentTransferPermissionSnapshotService,
)
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


@bisheng_celery.task(
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.permission.department_transfer_cleanup.process_event",
)
def process_event(event_id: int) -> bool:
    return run_async_task(lambda: _process_event_async(event_id))


@bisheng_celery.task(
    acks_late=True,
    time_limit=300,
    soft_time_limit=240,
    name="bisheng.worker.permission.department_transfer_cleanup.scan_due_events",
)
def scan_due_events() -> int:
    return run_async_task(_scan_due_events_async)


async def _process_event_async(event_id: int) -> bool:
    async with get_async_db_session() as session:
        repository = DepartmentTransferPermissionCleanupRepositoryImpl(session)
        event = await repository.find_by_id(event_id)
        if event is None:
            logger.warning("department transfer cleanup event not found event_id=%s", event_id)
            return False
        await _mark_overdue_if_needed(repository, event, now=datetime.now())
        await session.commit()
        service = DepartmentTransferPermissionCleanupService(
            session=session,
            repository=repository,
            snapshot_service=DepartmentTransferPermissionSnapshotService(
                session=session,
                repository=repository,
            ),
        )
        result = await service.process_event(event_id)
        return result.succeeded


async def _scan_due_events_async() -> int:
    now = datetime.now()
    dispatched = 0
    async with get_async_db_session() as session:
        repository = DepartmentTransferPermissionCleanupRepositoryImpl(session)
        for event in await repository.list_preparing_events(limit=100):
            current_department_id = await _load_primary_department(
                session,
                user_id=int(event.user_id),
            )
            if current_department_id == int(event.old_department_id):
                continue
            if current_department_id is None:
                logger.warning(
                    "department transfer preparing event cannot resolve primary department "
                    "event_id=%s user_id=%s source=%s",
                    event.id,
                    event.user_id,
                    event.trigger_source,
                )
                continue
            changed_at = datetime.now()
            await repository.activate_event(
                int(event.id),
                changed_at=changed_at,
                deadline_at=changed_at + timedelta(minutes=5),
            )
        await session.commit()

        event_ids = await repository.list_due_event_ids(now=now, limit=100)
        for event_id in event_ids:
            event = await repository.find_by_id(event_id)
            if event is None:
                continue
            await _mark_overdue_if_needed(repository, event, now=now)
            await session.commit()
            try:
                process_event.apply_async(args=[event_id], queue="knowledge_celery")
                dispatched += 1
            except Exception as exc:
                logger.warning(
                    "department transfer cleanup scan dispatch failed event_id=%s "
                    "user_id=%s old_department_id=%s new_department_id=%s "
                    "source=%s error_summary=%s",
                    event_id,
                    event.user_id,
                    event.old_department_id,
                    event.new_department_id,
                    event.trigger_source,
                    f"{type(exc).__name__}:operation_failed",
                )
    return dispatched


async def _mark_overdue_if_needed(repository, event, *, now: datetime) -> bool:
    if event.status in DepartmentTransferCleanupEventStatus.TERMINAL:
        return False
    first_mark = await repository.mark_event_overdue(int(event.id), now=now)
    if first_mark:
        logger.critical(
            "department transfer cleanup overdue event_id=%s user_id=%s "
            "old_department_id=%s new_department_id=%s source=%s status=%s "
            "retry_count=%s error_summary=%s",
            event.id,
            event.user_id,
            event.old_department_id,
            event.new_department_id,
            event.trigger_source,
            DepartmentTransferCleanupEventStatus.OVERDUE,
            event.retry_count,
            event.last_error or "none",
        )
    return first_mark


async def _load_primary_department(session, *, user_id: int) -> int | None:
    result = await session.execute(
        select(UserDepartment.department_id).where(
            UserDepartment.user_id == user_id,
            UserDepartment.is_primary == 1,
        )
    )
    value = result.scalar_one_or_none()
    return int(value) if value is not None else None
