from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
    DepartmentTransferCleanupEventStatus,
    DepartmentTransferCleanupItemStatus,
    DepartmentTransferCleanupItemType,
)
from bisheng.permission.domain.services.department_transfer_permission_cleanup_service import (
    DepartmentTransferPermissionCleanupService,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_succeeded"),
    [
        (DepartmentTransferCleanupEventStatus.SUCCEEDED, True),
        (DepartmentTransferCleanupEventStatus.CANCELLED, False),
    ],
)
async def test_terminal_event_result_only_reports_actual_success(
    status,
    expected_succeeded,
):
    event = SimpleNamespace(id=70, status=status)
    repository = SimpleNamespace(find_by_id=AsyncMock(return_value=event))
    service = DepartmentTransferPermissionCleanupService(
        session=SimpleNamespace(),
        repository=repository,
        permission_service=SimpleNamespace(),
        binding_service=SimpleNamespace(),
        file_grant_repository=SimpleNamespace(),
        cache_invalidator=AsyncMock(),
        projection_refresher=AsyncMock(),
        audit_writer=SimpleNamespace(),
        lock_factory=lambda _user_id: asyncio.Lock(),
    )

    result = await service.process_event(70)

    assert result.succeeded is expected_succeeded


@pytest.mark.asyncio
async def test_cleanup_revokes_tuple_binding_membership_and_file_grant():
    event = SimpleNamespace(
        id=71,
        tenant_id=1,
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source="local",
        status=DepartmentTransferCleanupEventStatus.PENDING,
        snapshot_complete=True,
        retry_count=0,
    )
    items = [
        SimpleNamespace(
            id=1,
            event_id=71,
            item_key="rebac_tuple:knowledge_space:100:viewer",
            item_type=DepartmentTransferCleanupItemType.REBAC_TUPLE,
            user_id=7,
            resource_type="knowledge_space",
            resource_id="100",
            root_space_id=100,
            relation="viewer",
            source_ref="binding-1",
            snapshot={"model_id": "custom-view", "binding_key": "binding-1"},
            status=DepartmentTransferCleanupItemStatus.PENDING,
        ),
        SimpleNamespace(
            id=2,
            event_id=71,
            item_key="space_membership:100",
            item_type=DepartmentTransferCleanupItemType.SPACE_MEMBERSHIP,
            user_id=7,
            resource_type="knowledge_space",
            resource_id="100",
            root_space_id=100,
            relation="viewer",
            source_ref="81",
            snapshot={"member_id": 81, "membership_source": "manual"},
            status=DepartmentTransferCleanupItemStatus.PENDING,
        ),
        SimpleNamespace(
            id=3,
            event_id=71,
            item_key="department_file_grant:100:301",
            item_type=DepartmentTransferCleanupItemType.DEPARTMENT_FILE_GRANT,
            user_id=7,
            resource_type="knowledge_file",
            resource_id="301",
            root_space_id=100,
            relation="viewer",
            source_ref="91",
            snapshot={
                "grant_id": 91,
                "approval_instance_id": 5001,
                "granted_at": "2026-07-24T09:00:00",
            },
            status=DepartmentTransferCleanupItemStatus.PENDING,
        ),
    ]
    repository = type(
        "Repository",
        (),
        {
            "find_by_id": AsyncMock(return_value=event),
            "claim_event": AsyncMock(return_value=True),
            "list_processable_items": AsyncMock(return_value=items),
            "transition_item": AsyncMock(return_value=True),
            "remove_membership_snapshot": AsyncMock(return_value="revoked"),
            "refresh_event_counts": AsyncMock(),
            "mark_event_succeeded": AsyncMock(return_value=event),
            "mark_event_failed": AsyncMock(),
        },
    )()
    permission_service = type("Permission", (), {"authorize": AsyncMock()})()
    binding_service = type(
        "Bindings",
        (),
        {"remove_binding_if_matches": AsyncMock(return_value=True)},
    )()
    file_grant = SimpleNamespace(
        id=91,
        tenant_id=1,
        user_id=7,
        space_id=100,
        file_id=301,
        department_id=10,
        approval_instance_id=5001,
        status="invalidated",
    )
    file_repository = type(
        "FileRepository",
        (),
        {"invalidate_snapshot_grant": AsyncMock(return_value=file_grant)},
    )()
    cache_invalidator = AsyncMock()
    projection_refresher = AsyncMock()
    audit_writer = type("Audit", (), {"add_transition": AsyncMock()})()
    service = DepartmentTransferPermissionCleanupService(
        session=SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock()),
        repository=repository,
        permission_service=permission_service,
        binding_service=binding_service,
        file_grant_repository=file_repository,
        cache_invalidator=cache_invalidator,
        projection_refresher=projection_refresher,
        audit_writer=audit_writer,
        lock_factory=lambda _user_id: asyncio.Lock(),
    )

    result = await service.process_event(71)

    assert result.succeeded is True
    permission_service.authorize.assert_awaited_once()
    binding_service.remove_binding_if_matches.assert_awaited_once_with(
        "binding-1",
        model_id="custom-view",
    )
    repository.remove_membership_snapshot.assert_awaited_once()
    file_repository.invalidate_snapshot_grant.assert_awaited_once()
    assert repository.transition_item.await_count == 3
    cache_invalidator.assert_awaited_once_with(7)
    projection_refresher.assert_awaited()
    repository.mark_event_succeeded.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_failure_stays_retryable_and_is_not_reported_as_success(
    caplog,
):
    event = SimpleNamespace(
        id=72,
        tenant_id=1,
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source="local",
        status=DepartmentTransferCleanupEventStatus.PENDING,
        snapshot_complete=True,
        retry_count=1,
    )
    item = SimpleNamespace(
        id=1,
        event_id=72,
        item_key="rebac_tuple:knowledge_space:100:viewer",
        item_type=DepartmentTransferCleanupItemType.REBAC_TUPLE,
        user_id=7,
        resource_type="knowledge_space",
        resource_id="100",
        root_space_id=100,
        relation="viewer",
        source_ref=None,
        snapshot={},
        status=DepartmentTransferCleanupItemStatus.PENDING,
    )
    repository = type(
        "Repository",
        (),
        {
            "find_by_id": AsyncMock(return_value=event),
            "claim_event": AsyncMock(return_value=True),
            "list_processable_items": AsyncMock(return_value=[item]),
            "transition_item": AsyncMock(return_value=True),
            "refresh_event_counts": AsyncMock(),
            "mark_event_succeeded": AsyncMock(),
            "mark_event_failed": AsyncMock(),
        },
    )()
    permission_service = type(
        "Permission",
        (),
        {"authorize": AsyncMock(side_effect=RuntimeError("fga token secret-value"))},
    )()
    service = DepartmentTransferPermissionCleanupService(
        session=SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock()),
        repository=repository,
        permission_service=permission_service,
        binding_service=SimpleNamespace(),
        file_grant_repository=SimpleNamespace(),
        cache_invalidator=AsyncMock(),
        projection_refresher=AsyncMock(),
        audit_writer=SimpleNamespace(),
        lock_factory=lambda _user_id: asyncio.Lock(),
    )

    with caplog.at_level("WARNING"):
        result = await service.process_event(72)

    assert result.succeeded is False
    repository.mark_event_succeeded.assert_not_awaited()
    repository.mark_event_failed.assert_awaited_once()
    error_summary = repository.mark_event_failed.await_args.kwargs["error_summary"]
    assert "secret-value" not in error_summary
    failure_log = next(record.getMessage() for record in caplog.records if "retryable failure" in record.getMessage())
    assert "event_id=72" in failure_log
    assert "user_id=7" in failure_log
    assert "old_department_id=10" in failure_log
    assert "new_department_id=20" in failure_log
    assert "source=local" in failure_log
    assert "secret-value" not in failure_log
    assert "secret-value" not in caplog.text


@pytest.mark.asyncio
async def test_cleanup_processes_more_than_one_hundred_items_in_reentrant_batches():
    event = SimpleNamespace(
        id=73,
        tenant_id=1,
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source="local",
        status=DepartmentTransferCleanupEventStatus.PENDING,
        snapshot_complete=True,
        retry_count=0,
    )
    items = [
        SimpleNamespace(
            id=index,
            event_id=73,
            item_key=f"unsupported:{index}",
            item_type="unsupported",
            user_id=7,
            resource_type="other",
            resource_id=str(index),
            root_space_id=None,
            relation=None,
            source_ref=None,
            snapshot={},
            status=DepartmentTransferCleanupItemStatus.PENDING,
        )
        for index in range(1, 102)
    ]
    repository = type(
        "Repository",
        (),
        {
            "find_by_id": AsyncMock(return_value=event),
            "claim_event": AsyncMock(return_value=True),
            "list_processable_items": AsyncMock(
                side_effect=[items[:100], items[100:]],
            ),
            "transition_item": AsyncMock(return_value=True),
            "refresh_event_counts": AsyncMock(),
            "mark_event_succeeded": AsyncMock(return_value=event),
            "mark_event_failed": AsyncMock(return_value=event),
        },
    )()
    service = DepartmentTransferPermissionCleanupService(
        session=SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock()),
        repository=repository,
        permission_service=SimpleNamespace(),
        binding_service=SimpleNamespace(),
        file_grant_repository=SimpleNamespace(),
        cache_invalidator=AsyncMock(),
        projection_refresher=AsyncMock(),
        audit_writer=SimpleNamespace(),
        lock_factory=lambda _user_id: asyncio.Lock(),
    )

    first = await service.process_event(73)
    second = await service.process_event(73)

    assert first.succeeded is False
    assert first.processed_count == 100
    assert second.succeeded is True
    assert second.processed_count == 1
    assert repository.transition_item.await_count == 101
    repository.mark_event_failed.assert_awaited_once()
    repository.mark_event_succeeded.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_dependency_recovers_on_later_retry():
    event = SimpleNamespace(
        id=74,
        tenant_id=1,
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source="local",
        status=DepartmentTransferCleanupEventStatus.PENDING,
        snapshot_complete=True,
        retry_count=0,
    )
    item = SimpleNamespace(
        id=1,
        event_id=74,
        item_key="rebac_tuple:knowledge_space:100:viewer",
        item_type=DepartmentTransferCleanupItemType.REBAC_TUPLE,
        user_id=7,
        resource_type="knowledge_space",
        resource_id="100",
        root_space_id=100,
        relation="viewer",
        source_ref=None,
        snapshot={},
        status=DepartmentTransferCleanupItemStatus.PENDING,
    )

    async def list_items(**_kwargs):
        return [item] if item.status in DepartmentTransferCleanupItemStatus.PROCESSABLE else []

    async def transition_item(_item_id, *, to_status, **_kwargs):
        item.status = to_status
        return True

    async def mark_failed(*_args, **_kwargs):
        event.status = DepartmentTransferCleanupEventStatus.FAILED
        event.retry_count += 1
        return event

    async def mark_succeeded(*_args, **_kwargs):
        event.status = DepartmentTransferCleanupEventStatus.SUCCEEDED
        return event

    repository = SimpleNamespace(
        find_by_id=AsyncMock(side_effect=lambda _event_id: event),
        claim_event=AsyncMock(return_value=True),
        list_processable_items=AsyncMock(side_effect=list_items),
        transition_item=AsyncMock(side_effect=transition_item),
        refresh_event_counts=AsyncMock(),
        mark_event_failed=AsyncMock(side_effect=mark_failed),
        mark_event_succeeded=AsyncMock(side_effect=mark_succeeded),
    )
    permission_service = SimpleNamespace(
        authorize=AsyncMock(
            side_effect=[
                RuntimeError("openfga temporarily unavailable"),
                None,
            ],
        ),
    )
    service = DepartmentTransferPermissionCleanupService(
        session=SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock()),
        repository=repository,
        permission_service=permission_service,
        binding_service=SimpleNamespace(),
        file_grant_repository=SimpleNamespace(),
        cache_invalidator=AsyncMock(),
        projection_refresher=AsyncMock(),
        audit_writer=SimpleNamespace(),
        lock_factory=lambda _user_id: asyncio.Lock(),
    )

    failed = await service.process_event(74)
    recovered = await service.process_event(74)

    assert failed.succeeded is False
    assert recovered.succeeded is True
    assert item.status == DepartmentTransferCleanupItemStatus.REVOKED
    assert event.status == DepartmentTransferCleanupEventStatus.SUCCEEDED
