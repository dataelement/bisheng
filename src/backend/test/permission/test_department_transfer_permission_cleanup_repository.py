from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
    DepartmentTransferCleanupEventStatus,
    DepartmentTransferCleanupItemStatus,
    DepartmentTransferCleanupItemType,
)
from bisheng.permission.domain.repositories.implementations.department_transfer_permission_cleanup_repository_impl import (
    DepartmentTransferPermissionCleanupRepositoryImpl,
)


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
