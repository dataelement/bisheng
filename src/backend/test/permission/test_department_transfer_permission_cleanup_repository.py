from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
    DepartmentTransferCleanupEventStatus,
    DepartmentTransferCleanupItemStatus,
    DepartmentTransferCleanupItemType,
)
from bisheng.permission.domain.repositories.implementations.department_transfer_permission_cleanup_repository_impl import (
    DepartmentTransferPermissionCleanupRepositoryImpl,
)
from bisheng.permission.domain.services.department_transfer_permission_cleanup_service import (
    DepartmentTransferPermissionCleanupService,
)


async def _retry_scenario(session, *, item_count=1, snapshot_complete=True):
    repository = DepartmentTransferPermissionCleanupRepositoryImpl(session)
    now = datetime.now()
    event = await repository.create_or_get_event(
        tenant_id=1,
        event_key="retry-cap",
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source="local",
        requested_at=now,
    )
    await repository.activate_event(event.id, changed_at=now, deadline_at=now + timedelta(minutes=5))
    await repository.set_snapshot_complete(event.id, complete=snapshot_complete)
    for index in range(item_count):
        await repository.upsert_item(
            tenant_id=1,
            event_id=event.id,
            item_key=f"file:{index}",
            item_type=DepartmentTransferCleanupItemType.REBAC_TUPLE,
            user_id=7,
            resource_type="knowledge_file",
            resource_id=str(index),
            root_space_id=100,
            relation="viewer",
            source_ref=None,
            snapshot={},
        )
    permission = SimpleNamespace(authorize=AsyncMock())
    snapshot = SimpleNamespace(capture=AsyncMock())
    service = DepartmentTransferPermissionCleanupService(
        session=session,
        repository=repository,
        permission_service=permission,
        snapshot_service=snapshot,
        binding_service=SimpleNamespace(),
        file_grant_repository=SimpleNamespace(),
        cache_invalidator=AsyncMock(),
        projection_refresher=AsyncMock(),
        audit_writer=SimpleNamespace(),
        lock_factory=lambda _user_id: asyncio.Lock(),
    )
    await session.commit()
    return repository, event, service, permission, snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["permission", "snapshot", "cache"])
async def test_cleanup_stops_after_three_failed_rounds(async_db_session, caplog, failure_stage):
    repository, event, service, permission, snapshot = await _retry_scenario(
        async_db_session,
        snapshot_complete=failure_stage != "snapshot",
    )
    failing_call = {
        "permission": permission.authorize,
        "snapshot": snapshot.capture,
        "cache": service.cache_invalidator,
    }[failure_stage]
    failing_call.side_effect = RuntimeError("dependency unavailable")
    event_id = event.id
    for _ in range(3):
        result = await service.process_event(event_id)
        assert result.succeeded is False
        event = await repository.find_by_id(event_id)
        if event.next_retry_at is not None:
            event.next_retry_at = datetime.now() - timedelta(seconds=1)
            await async_db_session.commit()

    assert event.status == "dead"
    assert event.retry_count == 3
    assert event.next_retry_at is None
    assert await repository.list_due_event_ids(now=datetime.now(), limit=100) == []
    assert (await service.process_event(event_id)).succeeded is False
    assert failing_call.await_count == 3
    if failure_stage != "snapshot":
        assert permission.authorize.await_count == 3
        assert all(call.kwargs["record_failures"] is False for call in permission.authorize.await_args_list)
    assert any(record.levelname == "CRITICAL" and f"event_id={event_id}" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_interrupted_cleanup_stops_before_fourth_execution(async_db_session):
    repository, event, service, permission, _ = await _retry_scenario(async_db_session)
    for _ in range(3):
        assert await repository.claim_event(event.id, now=datetime.now())
        event.next_retry_at = datetime.now() - timedelta(seconds=1)
        await async_db_session.commit()

    assert (await service.process_event(event.id)).succeeded is False
    permission.authorize.assert_not_awaited()
    await async_db_session.refresh(event)
    assert event.status == "dead"
    assert await repository.list_due_event_ids(now=datetime.now(), limit=100) == []
    await repository.activate_event(event.id, changed_at=datetime.now(), deadline_at=datetime.now())
    await repository.mark_event_succeeded(event.id, completed_at=datetime.now())
    assert event.status == "dead"


@pytest.mark.asyncio
async def test_successful_batches_do_not_exhaust_retry_budget(async_db_session):
    _, event, service, permission, _ = await _retry_scenario(async_db_session, item_count=401)
    # 兼容旧版本将正常分批也累计进 retry_count 的事件。
    event.retry_count = 8
    event.status = DepartmentTransferCleanupEventStatus.FAILED
    event.last_error = "batch_remaining"
    await async_db_session.commit()

    for _ in range(5):
        result = await service.process_event(event.id)

    assert result.succeeded is True
    assert permission.authorize.await_count == 401
    assert event.status == DepartmentTransferCleanupEventStatus.SUCCEEDED
    assert event.revoked_count == 401


@pytest.mark.asyncio
async def test_event_and_item_upsert_are_idempotent(async_db_session):
    repository = DepartmentTransferPermissionCleanupRepositoryImpl(async_db_session)
    requested_at = datetime(2026, 7, 24, 10, 0, 0)

    first = await repository.create_or_get_event(
        tenant_id=1,
        event_key="local:7:10:20:request-1",
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source="local",
        requested_at=requested_at,
    )
    duplicate = await repository.create_or_get_event(
        tenant_id=1,
        event_key="local:7:10:20:request-1",
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source="local",
        requested_at=requested_at,
    )

    assert first.id == duplicate.id
    assert first.status == DepartmentTransferCleanupEventStatus.PREPARING
    matching = await repository.find_active_matching_event(
        tenant_id=1,
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source="local",
    )
    assert matching and matching.id == first.id

    item = await repository.upsert_item(
        tenant_id=1,
        event_id=int(first.id),
        item_key="rebac_tuple:knowledge_space:99:viewer",
        item_type=DepartmentTransferCleanupItemType.REBAC_TUPLE,
        user_id=7,
        resource_type="knowledge_space",
        resource_id="99",
        root_space_id=99,
        relation="viewer",
        source_ref="binding-key",
        snapshot={"model_id": "viewer"},
    )
    await repository.protect_item(
        event_id=int(first.id),
        item_key=item.item_key,
        source="admin_grant",
        protected_at=requested_at + timedelta(seconds=1),
        tenant_id=1,
        user_id=7,
        item_type=DepartmentTransferCleanupItemType.REBAC_TUPLE,
        resource_type="knowledge_space",
        resource_id="99",
        relation="viewer",
        snapshot={"operation_id": "op-1"},
    )
    duplicate_item = await repository.upsert_item(
        tenant_id=1,
        event_id=int(first.id),
        item_key=item.item_key,
        item_type=DepartmentTransferCleanupItemType.REBAC_TUPLE,
        user_id=7,
        resource_type="knowledge_space",
        resource_id="99",
        root_space_id=99,
        relation="viewer",
        source_ref="binding-key",
        snapshot={"model_id": "viewer"},
    )

    assert duplicate_item.id == item.id
    assert duplicate_item.status == DepartmentTransferCleanupItemStatus.PROTECTED
    assert duplicate_item.protected_source == "admin_grant"


@pytest.mark.asyncio
async def test_claim_and_terminal_item_transitions_are_monotonic(async_db_session):
    repository = DepartmentTransferPermissionCleanupRepositoryImpl(async_db_session)
    now = datetime(2026, 7, 24, 10, 0, 0)
    event = await repository.create_or_get_event(
        tenant_id=1,
        event_key="org_sync:8:11:21:request-2",
        user_id=8,
        old_department_id=11,
        new_department_id=21,
        trigger_source="org_sync",
        requested_at=now,
    )
    await repository.activate_event(
        int(event.id),
        changed_at=now,
        deadline_at=now + timedelta(minutes=5),
    )

    assert await repository.claim_event(int(event.id), now=now) is True
    assert await repository.claim_event(int(event.id), now=now) is False

    item = await repository.upsert_item(
        tenant_id=1,
        event_id=int(event.id),
        item_key="space_membership:33",
        item_type=DepartmentTransferCleanupItemType.SPACE_MEMBERSHIP,
        user_id=8,
        resource_type="knowledge_space",
        resource_id="33",
        root_space_id=33,
        relation="viewer",
        source_ref="501",
        snapshot={"membership_source": "manual"},
    )
    assert await repository.transition_item(
        int(item.id),
        to_status=DepartmentTransferCleanupItemStatus.REVOKED,
        processed_at=now,
    )
    assert not await repository.transition_item(
        int(item.id),
        to_status=DepartmentTransferCleanupItemStatus.FAILED,
        processed_at=now,
        last_error="must not regress",
    )


@pytest.mark.asyncio
async def test_due_and_overdue_events_remain_retryable(async_db_session):
    repository = DepartmentTransferPermissionCleanupRepositoryImpl(async_db_session)
    changed_at = datetime(2026, 7, 24, 10, 0, 0)
    event = await repository.create_or_get_event(
        tenant_id=1,
        event_key="login_sync:9:12:22:request-3",
        user_id=9,
        old_department_id=12,
        new_department_id=22,
        trigger_source="login_sync",
        requested_at=changed_at,
    )
    await repository.activate_event(
        int(event.id),
        changed_at=changed_at,
        deadline_at=changed_at + timedelta(minutes=5),
    )
    await repository.mark_event_failed(
        int(event.id),
        error_summary="openfga_unavailable",
        next_retry_at=changed_at + timedelta(seconds=30),
    )

    assert (
        await repository.list_due_event_ids(
            now=changed_at + timedelta(seconds=29),
            limit=100,
        )
        == []
    )
    assert await repository.list_due_event_ids(
        now=changed_at + timedelta(seconds=30),
        limit=100,
    ) == [int(event.id)]

    assert await repository.mark_event_overdue(
        int(event.id),
        now=changed_at + timedelta(minutes=6),
    )
    overdue = await repository.find_by_id(int(event.id))
    assert overdue.status == DepartmentTransferCleanupEventStatus.OVERDUE
    assert overdue.overdue_at == changed_at + timedelta(minutes=6)
    assert await repository.list_due_event_ids(
        now=changed_at + timedelta(minutes=6),
        limit=100,
    ) == [int(event.id)]

    await repository.mark_event_succeeded(
        int(event.id),
        completed_at=changed_at + timedelta(minutes=7),
    )
    recovered = await repository.find_by_id(int(event.id))
    assert recovered.status == DepartmentTransferCleanupEventStatus.SUCCEEDED
    assert recovered.overdue_at == changed_at + timedelta(minutes=6)
