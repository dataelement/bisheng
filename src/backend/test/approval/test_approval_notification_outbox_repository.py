from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import UniqueConstraint, create_engine, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_notification_outbox import (
    ApprovalNotificationEventType,
    ApprovalNotificationOutbox,
    ApprovalNotificationOutboxStatus,
)
from bisheng.approval.domain.repositories.approval_notification_outbox_repository import (
    ApprovalNotificationOutboxRepository,
)
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.database.alembic.versions import v2_6_0_f058_approval_notification_outbox as migration


@pytest_asyncio.fixture
async def notification_outbox_repository(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: SQLModel.metadata.create_all(
                sync_connection,
                tables=[ApprovalNotificationOutbox.__table__],
            )
        )

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(bind=engine) as session:
            yield session

    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_notification_outbox_repository.get_async_db_session",
        session_factory,
    )
    yield ApprovalNotificationOutboxRepository
    await engine.dispose()


def _outbox(*, tenant_id: int, instance_id: int, retry_count: int = 0, max_retries: int = 3):
    return ApprovalNotificationOutbox(
        tenant_id=tenant_id,
        instance_id=instance_id,
        event_type=ApprovalNotificationEventType.FILE_PUBLISH_SUBMITTED,
        status=ApprovalNotificationOutboxStatus.PENDING,
        retry_count=retry_count,
        max_retries=max_retries,
        payload_snapshot={"task_ids": [instance_id + 100]},
    )


def test_notification_outbox_model_has_dedupe_and_dispatch_indexes():
    table = ApprovalNotificationOutbox.__table__
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    indexes = {index.name: tuple(column.name for column in index.columns) for index in table.indexes}

    assert ("tenant_id", "instance_id", "event_type") in unique_columns
    assert indexes["idx_approval_notification_outbox_dispatch"] == (
        "status",
        "retry_count",
        "update_time",
    )


@pytest.mark.asyncio
async def test_create_or_get_is_idempotent(notification_outbox_repository):
    token = set_current_tenant_id(1)
    try:
        first = await notification_outbox_repository.create_or_get(_outbox(tenant_id=1, instance_id=10))
        second = await notification_outbox_repository.create_or_get(_outbox(tenant_id=1, instance_id=10))
    finally:
        current_tenant_id.reset(token)

    assert first.id == second.id
    assert second.payload_snapshot == {"task_ids": [110]}


@pytest.mark.asyncio
async def test_update_failed_and_success_status(notification_outbox_repository):
    token = set_current_tenant_id(1)
    try:
        saved = await notification_outbox_repository.create_or_get(_outbox(tenant_id=1, instance_id=11))
        failed = await notification_outbox_repository.mark_failed(saved.id, "broker unavailable")
        success = await notification_outbox_repository.mark_success(saved.id)
    finally:
        current_tenant_id.reset(token)

    assert failed.retry_count == 1
    assert failed.status == ApprovalNotificationOutboxStatus.FAILED
    assert failed.error_summary == "broker unavailable"
    assert success.status == ApprovalNotificationOutboxStatus.SUCCESS
    assert success.error_summary is None


@pytest.mark.asyncio
async def test_list_dispatchable_cross_tenant_respects_retry_limit(notification_outbox_repository):
    for tenant_id, instance_id, retry_count in [(1, 20, 0), (2, 21, 1), (3, 22, 3)]:
        token = set_current_tenant_id(tenant_id)
        try:
            row = await notification_outbox_repository.create_or_get(
                _outbox(
                    tenant_id=tenant_id,
                    instance_id=instance_id,
                    retry_count=retry_count,
                )
            )
            if retry_count:
                row.status = ApprovalNotificationOutboxStatus.FAILED
                await notification_outbox_repository.save(row)
        finally:
            current_tenant_id.reset(token)

    rows = await notification_outbox_repository.list_dispatchable(limit=20)

    assert [(row.tenant_id, row.instance_id) for row in rows] == [(1, 20), (2, 21)]


def test_f058_migration_upgrade_and_downgrade():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        table_names = inspect(connection).get_table_names()
        assert "approval_notification_outbox" in table_names
        indexes = {item["name"] for item in inspect(connection).get_indexes("approval_notification_outbox")}
        assert "idx_approval_notification_outbox_dispatch" in indexes

        with Operations.context(context):
            migration.downgrade()
        assert "approval_notification_outbox" not in inspect(connection).get_table_names()
    engine.dispose()
