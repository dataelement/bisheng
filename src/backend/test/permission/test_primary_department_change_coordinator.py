from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.permission.domain.services.primary_department_change_coordinator import (
    PrimaryDepartmentChangeCoordinator,
)


@pytest.mark.asyncio
async def test_production_prepare_holds_user_lock_through_snapshot(monkeypatch):
    from bisheng.permission.domain.services import (
        department_transfer_grant_guard as guard_module,
    )
    from bisheng.permission.domain.services import (
        department_transfer_permission_snapshot_service as snapshot_module,
    )
    from bisheng.permission.domain.services import (
        primary_department_change_coordinator as coordinator_module,
    )

    lock_state = {"active": False}
    expected_lock_state = {"active": True}
    call_order: list[str] = []

    class _LockProbe:
        async def __aenter__(self):
            lock_state["active"] = True
            call_order.append("lock_enter")

        async def __aexit__(self, *_args):
            call_order.append("lock_exit")
            lock_state["active"] = False

    async def _capture(_event):
        assert lock_state["active"] is expected_lock_state["active"]
        call_order.append("snapshot")

    repository = SimpleNamespace(
        create_or_get_event=AsyncMock(
            return_value=SimpleNamespace(id=40, event_key="local:7:10:20:req"),
        ),
    )
    session = SimpleNamespace(commit=AsyncMock(side_effect=lambda: call_order.append("commit")))

    @asynccontextmanager
    async def _session_factory():
        yield session

    monkeypatch.setattr(
        guard_module,
        "_DepartmentTransferUserLock",
        lambda _user_id: _LockProbe(),
    )
    monkeypatch.setattr(coordinator_module, "get_async_db_session", _session_factory)
    monkeypatch.setattr(
        coordinator_module,
        "DepartmentTransferPermissionCleanupRepositoryImpl",
        lambda _session: repository,
    )
    monkeypatch.setattr(
        snapshot_module,
        "DepartmentTransferPermissionSnapshotService",
        lambda **_kwargs: SimpleNamespace(capture=AsyncMock(side_effect=_capture)),
    )

    prepared = await coordinator_module.prepare_primary_department_change(
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source="local",
        source_event_key="req",
    )

    assert prepared and prepared.event_id == 40
    assert call_order == ["lock_enter", "snapshot", "commit", "lock_exit"]

    class _UnavailableLock:
        async def __aenter__(self):
            raise guard_module.DepartmentTransferGrantRetryableError("redis unavailable")

        async def __aexit__(self, *_args):
            return None

    call_order.clear()
    expected_lock_state["active"] = False
    repository.create_or_get_event.return_value = SimpleNamespace(
        id=44,
        event_key="local:7:10:30:req-2",
    )
    monkeypatch.setattr(
        guard_module,
        "_DepartmentTransferUserLock",
        lambda _user_id: _UnavailableLock(),
    )

    fallback_prepared = await coordinator_module.prepare_primary_department_change(
        user_id=7,
        old_department_id=10,
        new_department_id=30,
        trigger_source="local",
        source_event_key="req-2",
    )

    assert fallback_prepared and fallback_prepared.event_id == 44
    assert call_order == ["snapshot", "commit"]


@pytest.mark.asyncio
async def test_prepare_activate_and_cancel_protocol():
    event = type("Event", (), {"id": 41})()
    repository = type(
        "Repository",
        (),
        {
            "create_or_get_event": AsyncMock(return_value=event),
            "activate_event": AsyncMock(return_value=event),
            "cancel_event": AsyncMock(return_value=event),
        },
    )()
    snapshot_service = type("Snapshot", (), {"capture": AsyncMock(return_value=True)})()
    dispatcher = AsyncMock()
    coordinator = PrimaryDepartmentChangeCoordinator(
        repository=repository,
        snapshot_service=snapshot_service,
        dispatcher=dispatcher,
        tenant_id=1,
    )

    assert (
        await coordinator.prepare_change(
            user_id=7,
            old_department_id=10,
            new_department_id=10,
            trigger_source="local",
            source_event_key="same",
        )
        is None
    )
    prepared = await coordinator.prepare_change(
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source="local",
        source_event_key="request-1",
    )
    assert prepared and prepared.event_id == 41
    snapshot_service.capture.assert_awaited_once_with(event)

    changed_at = datetime(2026, 7, 24, 11, 0, 0)
    await coordinator.activate_change(prepared, changed_at=changed_at)
    repository.activate_event.assert_awaited_once()
    assert repository.activate_event.await_args.kwargs["deadline_at"].minute == 5
    dispatcher.assert_awaited_once_with(41)

    await coordinator.cancel_change(prepared, reason="department update rolled back")
    repository.cancel_event.assert_awaited_once_with(
        41,
        reason="department update rolled back",
    )


@pytest.mark.asyncio
async def test_snapshot_or_dispatch_failure_does_not_block_department_change():
    event = type("Event", (), {"id": 42})()
    repository = type(
        "Repository",
        (),
        {
            "create_or_get_event": AsyncMock(return_value=event),
            "activate_event": AsyncMock(return_value=event),
            "set_snapshot_complete": AsyncMock(),
        },
    )()
    snapshot_service = type(
        "Snapshot",
        (),
        {"capture": AsyncMock(side_effect=RuntimeError("openfga unavailable"))},
    )()
    dispatcher = AsyncMock(side_effect=RuntimeError("queue unavailable"))
    coordinator = PrimaryDepartmentChangeCoordinator(
        repository=repository,
        snapshot_service=snapshot_service,
        dispatcher=dispatcher,
        tenant_id=1,
    )

    prepared = await coordinator.prepare_change(
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source="org_sync",
        source_event_key="request-2",
    )
    assert prepared and prepared.event_id == 42
    repository.set_snapshot_complete.assert_awaited_once()

    await coordinator.activate_change(
        prepared,
        changed_at=datetime(2026, 7, 24, 11, 0, 0),
    )
    repository.activate_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_equivalent_retry_reuses_unfinished_event_without_source_key():
    event = type(
        "Event",
        (),
        {
            "id": 43,
            "event_key": "active:local:7:10:20",
        },
    )()
    repository = type(
        "Repository",
        (),
        {
            "find_active_matching_event": AsyncMock(return_value=event),
            "create_or_get_event": AsyncMock(),
        },
    )()
    coordinator = PrimaryDepartmentChangeCoordinator(
        repository=repository,
        tenant_id=1,
    )

    prepared = await coordinator.prepare_change(
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source="local",
        source_event_key=None,
    )

    assert prepared and prepared.event_id == 43
    repository.create_or_get_event.assert_not_awaited()
