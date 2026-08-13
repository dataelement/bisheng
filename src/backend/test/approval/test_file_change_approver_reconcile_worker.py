from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id
from test.approval.test_file_change_execution_worker import _load_worker, fake_celery

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_WORKER_PATH = _BACKEND_ROOT / "bisheng" / "worker" / "knowledge" / "file_change_tasks.py"


@pytest.fixture
def worker():
    module = _load_worker()
    for task in fake_celery.tasks.values():
        task.apply_async.reset_mock()
        task.apply_async.side_effect = None
    return module


@pytest.fixture(autouse=True)
def reset_tenant_context():
    token = current_tenant_id.set(None)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


def test_dynamic_approver_tasks_are_registered_in_knowledge_worker_with_knowledge_queue(worker):
    expected = {
        "reconcile_space_file_change_approvers",
        "reconcile_tenant_file_change_approvers",
        "reconcile_all_file_change_approvers",
    }
    assert expected.issubset(fake_celery.tasks)
    for name in expected:
        options = fake_celery.tasks[name].options
        assert options["acks_late"] is True
        assert options["queue"] == "knowledge_celery"
        assert options["autoretry_for"] == (Exception,)


def test_dynamic_reconcile_uses_permission_dispatcher_and_never_runtime_handler():
    source = _WORKER_PATH.read_text(encoding="utf-8")
    assert "FileChangeApproverReconcileDispatcher" in source
    assert "_build_approver_reconcile_dispatcher" in source
    forbidden = ("build_runtime_handler", "KnowledgeSpaceFileChangeScenarioHandler", "approval_instance_repository")
    for fragment in forbidden:
        assert fragment not in source


def test_space_reconcile_restores_explicit_tenant_context(worker, monkeypatch: pytest.MonkeyPatch):
    observed: list[int | None] = []

    def run(factory):
        observed.append(get_current_tenant_id())
        coroutine = factory()
        coroutine.close()
        return {"status": "ok"}

    monkeypatch.setattr(worker, "run_async_task", run)
    outer = set_current_tenant_id(99)
    try:
        result = worker.reconcile_space_file_change_approvers(
            SimpleNamespace(request=SimpleNamespace(headers={"tenant_id": 23})),
            space_id=8,
            reason="permission_event",
        )
        assert result == {"status": "ok"}
        assert observed == [23]
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(outer)


async def test_space_reconcile_calls_permission_dispatcher_contract(worker, monkeypatch: pytest.MonkeyPatch):
    dispatcher = SimpleNamespace(reconcile_space=AsyncMock(return_value=2))
    monkeypatch.setattr(worker, "_build_approver_reconcile_dispatcher", lambda: dispatcher)

    assert await worker._reconcile_space_async(
        tenant_id=23,
        space_id=8,
        reason="permission_event",
    ) == {"reconciled": 2}
    dispatcher.reconcile_space.assert_awaited_once_with(
        tenant_id=23,
        space_id=8,
        reason="permission_event",
    )


async def test_cross_tenant_reconcile_dispatch_isolates_broker_failure_and_sets_headers(
    worker,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(worker, "_load_active_tenant_ids", AsyncMock(return_value=[11, 12, 13]))

    def dispatch(*, kwargs, headers):
        assert kwargs == {"after_update_time": None, "after_request_id": 0}
        assert headers == {"tenant_id": headers["tenant_id"]}
        if headers["tenant_id"] == 12:
            raise RuntimeError("broker unavailable")

    worker.reconcile_tenant_file_change_approvers.apply_async.side_effect = dispatch

    result = await worker._coordinate_reconcile_all_tenants_async()

    assert result == {"processed": 3, "dispatched": 2, "failed": 1}
    assert [
        call.kwargs["headers"] for call in worker.reconcile_tenant_file_change_approvers.apply_async.call_args_list
    ] == [
        {"tenant_id": 11},
        {"tenant_id": 12},
        {"tenant_id": 13},
    ]


def test_all_tenant_task_executes_async_coordinator(worker, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(worker, "run_async_task", lambda factory: asyncio.run(factory()))
    monkeypatch.setattr(
        worker,
        "_coordinate_reconcile_all_tenants_async",
        AsyncMock(return_value={"processed": 0, "dispatched": 0, "failed": 0}),
    )
    assert worker.reconcile_all_file_change_approvers() == {"processed": 0, "dispatched": 0, "failed": 0}
