from __future__ import annotations

# ruff: noqa: E402, I001 -- fake Celery modules must be installed before loading the worker module.

import importlib.util
import sys
import types
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

for module_name in (
    "celery",
    "celery.signals",
    "celery.schedules",
    "celery.app",
    "celery.app.task",
):
    if module_name not in sys.modules:
        sys.modules[module_name] = MagicMock()

from test.fixtures.mock_services import premock_import_chain

premock_import_chain()


class _FakeTask:
    def __init__(self, function, options: dict) -> None:
        self.function = function
        self.options = options
        self.apply_async = MagicMock()

    def __call__(self, *args, **kwargs):
        return self.function(*args, **kwargs)


class _FakeCelery:
    def __init__(self) -> None:
        self.tasks: dict[str, _FakeTask] = {}

    def task(self, *decorator_args, **options):
        def decorate(function):
            task = _FakeTask(function, options)
            self.tasks[function.__name__] = task
            return task

        if decorator_args and callable(decorator_args[0]) and len(decorator_args) == 1:
            return decorate(decorator_args[0])
        return decorate


fake_celery = _FakeCelery()
fake_worker_package = types.ModuleType("bisheng.worker")
fake_worker_package.__path__ = []  # type: ignore[attr-defined]
sys.modules["bisheng.worker"] = fake_worker_package

fake_worker_main = types.ModuleType("bisheng.worker.main")
fake_worker_main.bisheng_celery = fake_celery
sys.modules["bisheng.worker.main"] = fake_worker_main

fake_asyncio_utils = types.ModuleType("bisheng.worker._asyncio_utils")
fake_asyncio_utils.run_async_task = MagicMock()
sys.modules["bisheng.worker._asyncio_utils"] = fake_asyncio_utils

from bisheng.approval.domain.models.approval_decision_outbox import (
    ApprovalDecisionOutboxStatus,
)
from bisheng.approval.domain.ports.decision_subscriber import (
    ApprovalDecisionRetryableError,
)
from bisheng.core.context.tenant import (
    current_tenant_id,
    get_current_tenant_id,
    set_current_tenant_id,
)

_WORKER_PATH = Path(__file__).resolve().parents[2] / "bisheng" / "worker" / "approval" / "decision_delivery_tasks.py"
_WORKER_SPEC = importlib.util.spec_from_file_location(
    "approval_decision_delivery_worker_test_module",
    _WORKER_PATH,
)
assert _WORKER_SPEC and _WORKER_SPEC.loader
_WORKER_MODULE = importlib.util.module_from_spec(_WORKER_SPEC)
_WORKER_SPEC.loader.exec_module(_WORKER_MODULE)

deliver_approval_decision = _WORKER_MODULE.deliver_approval_decision
coordinate_approval_decision_delivery = _WORKER_MODULE.coordinate_approval_decision_delivery
_deliver_one_async = _WORKER_MODULE._deliver_one_async
_coordinate_recoverable_async = _WORKER_MODULE._coordinate_recoverable_async


@pytest.fixture(autouse=True)
def reset_worker_state():
    token = current_tenant_id.set(None)
    for task in fake_celery.tasks.values():
        task.apply_async.reset_mock()
        task.apply_async.side_effect = None
    yield
    current_tenant_id.reset(token)


def test_worker_tasks_use_default_queue_and_single_event_exponential_backoff():
    assert {
        "deliver_approval_decision",
        "coordinate_approval_decision_delivery",
    }.issubset(fake_celery.tasks)

    delivery_options = fake_celery.tasks["deliver_approval_decision"].options
    assert delivery_options["bind"] is True
    assert delivery_options["acks_late"] is True
    assert delivery_options["autoretry_for"] == (ApprovalDecisionRetryableError,)
    assert delivery_options["retry_backoff"] is True
    assert delivery_options["retry_jitter"] is True
    assert delivery_options["retry_kwargs"]["max_retries"] > 0
    assert "queue" not in delivery_options

    coordinator_options = fake_celery.tasks["coordinate_approval_decision_delivery"].options
    assert coordinator_options["bind"] is True
    assert coordinator_options["acks_late"] is True
    assert "queue" not in coordinator_options


@pytest.mark.parametrize(
    "task_name,args",
    [
        ("deliver_approval_decision", ()),
        ("coordinate_approval_decision_delivery", ()),
    ],
)
def test_tasks_restore_explicit_tenant_header_context(
    monkeypatch: pytest.MonkeyPatch,
    task_name: str,
    args: tuple,
):
    observed: list[int | None] = []

    def fake_run_async_task(coroutine_factory):
        observed.append(get_current_tenant_id())
        coroutine = coroutine_factory()
        coroutine.close()
        return {"ok": True}

    monkeypatch.setattr(_WORKER_MODULE, "run_async_task", fake_run_async_task)
    outer_token = set_current_tenant_id(99)
    try:
        task = getattr(_WORKER_MODULE, task_name)
        result = task(
            SimpleNamespace(request=SimpleNamespace(headers={"tenant_id": "23"})),
            *args,
        )
        assert result == {"ok": True}
        assert observed == [23]
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(outer_token)


def test_task_restores_outer_context_when_delivery_raises(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        _WORKER_MODULE,
        "run_async_task",
        MagicMock(side_effect=ApprovalDecisionRetryableError("ack unavailable")),
    )
    outer_token = set_current_tenant_id(99)
    try:
        with pytest.raises(ApprovalDecisionRetryableError, match="ack unavailable"):
            deliver_approval_decision(SimpleNamespace(request=SimpleNamespace(headers={"tenant_id": 23})))
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(outer_token)


@pytest.mark.parametrize(
    "headers",
    [
        None,
        {},
        {"tenant_id": None},
        {"tenant_id": True},
        {"tenant_id": "bad"},
        {"tenant_id": 0},
        {"tenant_id": -1},
    ],
)
def test_tasks_fail_closed_without_positive_tenant_header(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict | None,
):
    run_async_task = MagicMock()
    monkeypatch.setattr(_WORKER_MODULE, "run_async_task", run_async_task)

    with pytest.raises(ValueError, match="tenant_id header"):
        deliver_approval_decision(SimpleNamespace(request=SimpleNamespace(headers=headers)))

    run_async_task.assert_not_called()


async def test_single_delivery_reports_stable_event_id_not_broker_task_id(
    monkeypatch: pytest.MonkeyPatch,
):
    service = SimpleNamespace(deliver_next=AsyncMock(return_value=SimpleNamespace(event_id=91)))
    monkeypatch.setattr(
        _WORKER_MODULE,
        "_build_delivery_service",
        lambda: service,
    )

    result = await _deliver_one_async(tenant_id=23)

    service.deliver_next.assert_awaited_once_with(tenant_id=23)
    assert result == {"claimed": True, "event_id": 91}
    assert "task_id" not in result
    assert "delivered" not in result


async def test_single_delivery_returns_no_claim_without_inventing_completion(
    monkeypatch: pytest.MonkeyPatch,
):
    service = SimpleNamespace(deliver_next=AsyncMock(return_value=None))
    monkeypatch.setattr(
        _WORKER_MODULE,
        "_build_delivery_service",
        lambda: service,
    )

    result = await _deliver_one_async(tenant_id=23)

    assert result == {"claimed": False, "event_id": None}
    assert "delivered" not in result


class _FakeRecoveryRepository:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows
        self.calls: list[dict] = []

    async def list_recoverable(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.rows)


@asynccontextmanager
async def _fake_session_factory():
    yield SimpleNamespace()


async def test_coordinator_scans_one_bounded_lease_reclaim_page_with_headers(
    monkeypatch: pytest.MonkeyPatch,
):
    now = datetime(2026, 8, 13, 11, 0, 0)
    rows = [
        SimpleNamespace(
            id=11,
            status=ApprovalDecisionOutboxStatus.PROCESSING,
            claim_deadline=now - timedelta(seconds=1),
        ),
        SimpleNamespace(
            id=12,
            status=ApprovalDecisionOutboxStatus.PENDING,
            claim_deadline=None,
        ),
        SimpleNamespace(
            id=13,
            status=ApprovalDecisionOutboxStatus.PENDING,
            claim_deadline=None,
        ),
    ]
    repository = _FakeRecoveryRepository(rows)
    monkeypatch.setattr(
        _WORKER_MODULE,
        "get_async_db_session",
        _fake_session_factory,
    )
    monkeypatch.setattr(
        _WORKER_MODULE,
        "ApprovalDecisionOutboxRepository",
        lambda _session: repository,
    )
    monkeypatch.setattr(_WORKER_MODULE, "_utc_now", lambda: now)
    delivery_results = [
        SimpleNamespace(id="broker-task-11"),
        SimpleNamespace(id="broker-task-12"),
    ]
    deliver_approval_decision.apply_async.side_effect = delivery_results
    coordinate_approval_decision_delivery.apply_async.return_value = SimpleNamespace(id="coordinator-next-page")

    result = await _coordinate_recoverable_async(
        tenant_id=23,
        after_event_id=0,
        limit=2,
    )

    assert repository.calls == [
        {
            "tenant_id": 23,
            "now": now,
            "after_outbox_id": 0,
            "limit": 3,
        }
    ]
    assert deliver_approval_decision.apply_async.call_count == 2
    for call in deliver_approval_decision.apply_async.call_args_list:
        assert call.kwargs == {"headers": {"tenant_id": 23}}
    coordinate_approval_decision_delivery.apply_async.assert_called_once_with(
        kwargs={"after_event_id": 12},
        headers={"tenant_id": 23},
    )
    assert result == {
        "scanned": 2,
        "dispatched": 2,
        "dispatch_failed": 0,
        "has_more": True,
        "next_after_event_id": 12,
        "broker_task_ids": ["broker-task-11", "broker-task-12"],
        "continuation_task_id": "coordinator-next-page",
    }
    assert "delivered" not in result
    assert [row.status for row in rows] == [
        ApprovalDecisionOutboxStatus.PROCESSING,
        ApprovalDecisionOutboxStatus.PENDING,
        ApprovalDecisionOutboxStatus.PENDING,
    ]


async def test_one_dispatch_failure_does_not_block_later_recoverable_events(
    monkeypatch: pytest.MonkeyPatch,
):
    rows = [
        SimpleNamespace(id=21),
        SimpleNamespace(id=22),
    ]
    repository = _FakeRecoveryRepository(rows)
    monkeypatch.setattr(
        _WORKER_MODULE,
        "get_async_db_session",
        _fake_session_factory,
    )
    monkeypatch.setattr(
        _WORKER_MODULE,
        "ApprovalDecisionOutboxRepository",
        lambda _session: repository,
    )
    monkeypatch.setattr(
        _WORKER_MODULE,
        "_utc_now",
        lambda: datetime(2026, 8, 13, 11, 0, 0),
    )
    deliver_approval_decision.apply_async.side_effect = [
        RuntimeError("broker refused first task"),
        SimpleNamespace(id="broker-task-22"),
    ]

    result = await _coordinate_recoverable_async(
        tenant_id=23,
        after_event_id=0,
        limit=2,
    )

    assert deliver_approval_decision.apply_async.call_count == 2
    assert result["scanned"] == 2
    assert result["dispatched"] == 1
    assert result["dispatch_failed"] == 1
    assert result["broker_task_ids"] == ["broker-task-22"]
    assert result["has_more"] is False
    assert "delivered" not in result
