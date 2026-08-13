from __future__ import annotations

# ruff: noqa: E402, I001 -- fake Celery modules must exist before importing the worker.

import asyncio
import importlib.util
import inspect
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

for module_name in ("celery", "celery.signals", "celery.schedules", "celery.app", "celery.app.task"):
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
fake_worker_pkg = types.ModuleType("bisheng.worker")
fake_worker_pkg.__path__ = []  # type: ignore[attr-defined]
sys.modules["bisheng.worker"] = fake_worker_pkg

fake_worker_main = types.ModuleType("bisheng.worker.main")
fake_worker_main.bisheng_celery = fake_celery
sys.modules["bisheng.worker.main"] = fake_worker_main

fake_asyncio_utils = types.ModuleType("bisheng.worker._asyncio_utils")
fake_asyncio_utils.run_async_task = MagicMock()
sys.modules["bisheng.worker._asyncio_utils"] = fake_asyncio_utils

from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.services.knowledge_space_file_change_execution_coordinator import (
    ExecutionIdentity,
    ExecutionReconcileStatus,
    ExecutionStepContext,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_WORKER_PATH = _BACKEND_ROOT / "bisheng" / "worker" / "knowledge" / "file_change_tasks.py"
_OLD_WORKER_PATH = _BACKEND_ROOT / "bisheng" / "worker" / "approval" / "file_change_tasks.py"


def _load_worker():
    assert _WORKER_PATH.exists(), "T049 must move all F046 tasks to worker/knowledge/file_change_tasks.py"
    fake_celery.tasks.clear()
    spec = importlib.util.spec_from_file_location("file_change_execution_worker_test_module", _WORKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _MissingWorker:
    def __getattr__(self, name: str):
        pytest.fail(f"T049 must create worker/knowledge/file_change_tasks.py before {name!r} can be exercised")


@pytest.fixture
def worker():
    if not _WORKER_PATH.exists():
        return _MissingWorker()
    return _load_worker()


@pytest.fixture(autouse=True)
def reset_tenant_context():
    token = current_tenant_id.set(None)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


def _task_request(tenant_id: int = 23):
    return SimpleNamespace(headers={"tenant_id": tenant_id})


def _identity(token: str = "generation-1") -> ExecutionIdentity:
    return ExecutionIdentity(tenant_id=23, request_id=41, execution_token=token)


def _run_coroutine(monkeypatch: pytest.MonkeyPatch, worker) -> None:
    monkeypatch.setattr(worker, "run_async_task", lambda factory: asyncio.run(factory()))


def test_all_f046_tasks_are_owned_by_knowledge_and_never_import_approval():
    assert _WORKER_PATH.exists(), "T049 must create the Knowledge-owned F046 worker module"
    assert not _OLD_WORKER_PATH.exists(), "T049 must delete the Approval-owned F046 worker module"
    source = _WORKER_PATH.read_text(encoding="utf-8")
    forbidden = (
        "bisheng.approval",
        "ApprovalInstance",
        "ApprovalOutbox",
        "outbox_id",
        "instance_id",
        "build_runtime_handler",
        "payload_snapshot",
    )
    for fragment in forbidden:
        assert fragment not in source
    assert "bisheng.worker.knowledge.file_change_tasks" in source


def test_execution_tasks_are_retryable_acks_late_and_explicitly_use_knowledge_queue(worker):
    expected = {
        "coordinate_file_change_execution",
        "watchdog_file_change_execution",
        "execute_file_change_step",
        "acknowledge_file_change_upload_pipeline",
        "cleanup_file_change_upload_stage",
        "cleanup_orphan_file_change_upload_stage",
        "purge_file_change_delete",
        "cleanup_file_change_mutation",
        "continue_file_change_compensation",
        "watchdog_tenant_file_change_executions",
        "watchdog_all_file_change_executions",
        "compensate_tenant_file_change_execution_steps",
        "compensate_all_file_change_execution_steps",
        "cleanup_tenant_file_change_residue",
        "cleanup_all_file_change_residue",
    }
    assert expected.issubset(fake_celery.tasks)
    for name in expected:
        options = fake_celery.tasks[name].options
        assert options["acks_late"] is True
        assert options["autoretry_for"] == (Exception,)
        assert options["retry_backoff"] is True
        assert options["retry_jitter"] is True
        assert options["retry_kwargs"]["max_retries"] > 0
        assert options["queue"] == "knowledge_celery"


def test_broker_identity_never_accepts_approval_ids(worker):
    task_names = (
        "coordinate_file_change_execution",
        "watchdog_file_change_execution",
        "execute_file_change_step",
        "acknowledge_file_change_upload_pipeline",
        "purge_file_change_delete",
        "cleanup_file_change_mutation",
        "continue_file_change_compensation",
    )
    for task_name in task_names:
        parameters = inspect.signature(getattr(worker, task_name).function).parameters
        assert "outbox_id" not in parameters
        assert "instance_id" not in parameters
        assert "request_id" in parameters
    assert "execution_token" in inspect.signature(worker.execute_file_change_step.function).parameters


@pytest.mark.parametrize(
    "task_name,kwargs",
    [
        ("coordinate_file_change_execution", {"request_id": 41, "execution_token": "generation-1"}),
        ("watchdog_file_change_execution", {"request_id": 41, "execution_token": "generation-1"}),
        ("purge_file_change_delete", {"request_id": 41, "execution_token": "generation-1"}),
        ("cleanup_file_change_mutation", {"request_id": 41, "execution_token": "generation-1"}),
        ("continue_file_change_compensation", {"request_id": 41, "execution_token": "generation-1"}),
    ],
)
def test_worker_restores_outer_tenant_context(worker, monkeypatch, task_name: str, kwargs: dict):
    observed: list[int | None] = []

    def fake_run(factory):
        observed.append(get_current_tenant_id())
        coroutine = factory()
        coroutine.close()
        return {"status": "ok"}

    monkeypatch.setattr(worker, "run_async_task", fake_run)
    outer = set_current_tenant_id(99)
    try:
        task = getattr(worker, task_name)
        assert task(SimpleNamespace(request=_task_request()), **kwargs) == {"status": "ok"}
        assert observed == [23]
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(outer)


@pytest.mark.parametrize(
    "headers",
    [None, {}, {"tenant_id": None}, {"tenant_id": True}, {"tenant_id": "bad"}, {"tenant_id": 0}],
)
def test_worker_fails_closed_without_positive_tenant_header(worker, monkeypatch, headers):
    run = MagicMock()
    monkeypatch.setattr(worker, "run_async_task", run)
    with pytest.raises(ValueError, match="tenant_id header"):
        worker.execute_file_change_step(
            SimpleNamespace(request=SimpleNamespace(headers=headers)),
            request_id=41,
            execution_token="generation-1",
            action="rename",
            step_code="rename.index_shadow",
            idempotency_key="f046:41:rename.index_shadow",
        )
    run.assert_not_called()


async def test_step_dispatch_uses_stable_key_request_token_and_tenant_header(worker):
    context = ExecutionStepContext(
        tenant_id=23,
        request_id=41,
        execution_token="generation-1",
        action="rename",
        step_code="rename.index_shadow",
        idempotency_key="f046:41:rename.index_shadow",
        task_id=None,
    )

    task_id = await worker._dispatch_file_change_step(context)

    call = worker.execute_file_change_step.apply_async.call_args
    assert call.kwargs["task_id"] == "f046:41:rename.index_shadow"
    assert call.kwargs["headers"] == {"tenant_id": 23}
    assert call.kwargs["kwargs"] == {
        "request_id": 41,
        "execution_token": "generation-1",
        "action": "rename",
        "step_code": "rename.index_shadow",
        "idempotency_key": "f046:41:rename.index_shadow",
    }
    assert task_id == "f046:41:rename.index_shadow"


def test_execution_step_loads_current_business_identity_before_owner_verification(worker, monkeypatch):
    _run_coroutine(monkeypatch, worker)
    coordinator = SimpleNamespace(
        load_identity_by_request=AsyncMock(return_value=_identity()),
        acknowledge_step=AsyncMock(return_value=ExecutionReconcileStatus.COMPLETED),
    )
    executor = SimpleNamespace(execute_and_verify_step=AsyncMock())
    monkeypatch.setattr(worker, "_build_execution_coordinator", lambda: coordinator)
    monkeypatch.setattr(worker, "_build_mutation_executor", lambda: executor)

    result = worker.execute_file_change_step(
        SimpleNamespace(request=_task_request()),
        request_id=41,
        execution_token="generation-1",
        action="rename",
        step_code="rename.index_shadow",
        idempotency_key="f046:41:rename.index_shadow",
    )

    assert result == {"status": "completed"}
    coordinator.load_identity_by_request.assert_awaited_once_with(
        tenant_id=23,
        request_id=41,
        execution_token="generation-1",
    )
    coordinator.acknowledge_step.assert_awaited_once_with(
        identity=_identity(),
        step_code="rename.index_shadow",
        verifier=executor.execute_and_verify_step,
    )


def test_upload_ack_reloads_current_request_and_uses_owner_verifier(worker, monkeypatch):
    _run_coroutine(monkeypatch, worker)
    coordinator = SimpleNamespace(
        load_identity_by_request=AsyncMock(return_value=_identity()),
        acknowledge_step=AsyncMock(return_value=ExecutionReconcileStatus.COMPLETED),
    )
    executor = SimpleNamespace(execute_and_verify_step=AsyncMock())
    monkeypatch.setattr(worker, "_build_execution_coordinator", lambda: coordinator)
    monkeypatch.setattr(worker, "_build_mutation_executor", lambda: executor)

    result = worker.acknowledge_file_change_upload_pipeline(
        SimpleNamespace(request=_task_request()),
        request_id=41,
        execution_token="generation-1",
        file_id=71,
    )

    assert result == {"status": "completed"}
    coordinator.load_identity_by_request.assert_awaited_once_with(
        tenant_id=23,
        request_id=41,
        execution_token="generation-1",
    )
    coordinator.acknowledge_step.assert_awaited_once_with(
        identity=_identity(),
        step_code="upload.parse",
        verifier=executor.execute_and_verify_step,
        acknowledgement={"file_id": 71},
    )


def test_watchdog_is_token_bound_and_only_fails_current_knowledge_request(worker, monkeypatch):
    _run_coroutine(monkeypatch, worker)
    coordinator = SimpleNamespace(
        load_identity_by_request=AsyncMock(side_effect=[None, _identity()]),
        fail=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(worker, "_build_execution_coordinator", lambda: coordinator)

    stale = worker.watchdog_file_change_execution(
        SimpleNamespace(request=_task_request()),
        request_id=41,
        execution_token="old-generation",
    )
    current = worker.watchdog_file_change_execution(
        SimpleNamespace(request=_task_request()),
        request_id=41,
        execution_token="generation-1",
        heartbeat_timeout_seconds=900,
    )

    assert stale == {"status": "ignored"}
    assert current == {"status": "failed"}
    coordinator.fail.assert_awaited_once_with(
        identity=_identity(),
        error_summary="business execution watchdog timeout",
        watchdog=True,
        heartbeat_timeout_seconds=900,
    )


async def test_watchdog_scan_dispatches_only_request_token_and_request_cursor(worker, monkeypatch):
    page = SimpleNamespace(
        items=[SimpleNamespace(request_id=41, execution_token="generation-1")],
        has_more=True,
        next_after_id=41,
    )
    service = SimpleNamespace(list_watchdog_page=AsyncMock(return_value=page))
    monkeypatch.setattr(worker, "_build_compensation_service", lambda: service)

    result = await worker._watchdog_tenant_page_async(tenant_id=23, after_request_id=0)

    assert result == {"processed": 1, "dispatched": 1, "failed": 0, "has_more": True}
    service.list_watchdog_page.assert_awaited_once_with(
        tenant_id=23,
        after_request_id=0,
        limit=worker.COMPENSATION_BATCH_SIZE,
    )
    worker.watchdog_file_change_execution.apply_async.assert_called_once_with(
        kwargs={"request_id": 41, "execution_token": "generation-1"},
        headers={"tenant_id": 23},
    )
    worker.watchdog_tenant_file_change_executions.apply_async.assert_called_once_with(
        kwargs={"after_request_id": 41},
        headers={"tenant_id": 23},
    )


async def test_step_scan_deduplicates_current_business_generation(worker, monkeypatch):
    page = SimpleNamespace(
        items=[
            SimpleNamespace(
                step_id=301,
                request_id=41,
                execution_token="generation-1",
                execution_state="applying",
            ),
            SimpleNamespace(
                step_id=302,
                request_id=41,
                execution_token="generation-1",
                execution_state="applying",
            ),
            SimpleNamespace(
                step_id=303,
                request_id=42,
                execution_token="generation-2",
                execution_state="compensating",
            ),
        ],
        has_more=False,
        next_after_id=303,
    )
    service = SimpleNamespace(list_step_recovery_page=AsyncMock(return_value=page))
    monkeypatch.setattr(worker, "_build_compensation_service", lambda: service)

    result = await worker._compensate_tenant_step_page_async(tenant_id=23, after_step_id=0)

    assert result == {"processed": 3, "dispatched": 2, "failed": 0, "has_more": False}
    worker.coordinate_file_change_execution.apply_async.assert_called_once_with(
        kwargs={"request_id": 41, "execution_token": "generation-1"},
        headers={"tenant_id": 23},
    )
    worker.continue_file_change_compensation.apply_async.assert_called_once_with(
        kwargs={"request_id": 42, "execution_token": "generation-2"},
        headers={"tenant_id": 23},
    )


def test_stage_cleanup_is_an_idempotent_knowledge_service_call(worker, monkeypatch):
    _run_coroutine(monkeypatch, worker)
    service = SimpleNamespace(cleanup=AsyncMock(return_value=SimpleNamespace(cleanup_state="success")))
    monkeypatch.setattr(worker, "_build_file_change_service", lambda: service)

    result = worker.cleanup_file_change_upload_stage(
        SimpleNamespace(request=_task_request()),
        request_id=41,
        upload_id="opaque-1",
        terminal_action="rejected",
    )

    assert result == {"cleanup_state": "success"}
    service.cleanup.assert_awaited_once_with(
        tenant_id=23,
        request_id=41,
        upload_id="opaque-1",
        terminal_action="rejected",
        reason=None,
    )


async def test_decision_dispatcher_and_initial_coordinate_use_request_only(worker, monkeypatch):
    dispatcher = worker.CeleryKnowledgeSpaceFileChangeDispatcher()
    await dispatcher.dispatch(tenant_id=23, request_id=41)
    worker.coordinate_file_change_execution.apply_async.assert_called_once_with(
        kwargs={"request_id": 41},
        headers={"tenant_id": 23},
    )

    identity = _identity()
    coordinator = SimpleNamespace(
        begin_execution=AsyncMock(return_value=identity),
        load_identity_by_request=AsyncMock(),
        dispatch_ready_steps=AsyncMock(return_value=[]),
        reconcile=AsyncMock(return_value=ExecutionReconcileStatus.RUNNING),
    )
    monkeypatch.setattr(worker, "_build_execution_coordinator", lambda: coordinator)

    assert await worker._coordinate_execution_async(
        tenant_id=23,
        request_id=41,
        execution_token=None,
    ) == {"status": "running"}
    coordinator.begin_execution.assert_awaited_once_with(tenant_id=23, request_id=41)
    coordinator.load_identity_by_request.assert_not_awaited()


@pytest.mark.parametrize("tenant_id,request_id", [(True, 41), (23, True), (0, 41), (23, 0)])
async def test_decision_dispatcher_rejects_invalid_ids(worker, tenant_id, request_id):
    dispatcher = worker.CeleryKnowledgeSpaceFileChangeDispatcher()
    with pytest.raises(ValueError, match="positive tenant_id and request_id"):
        await dispatcher.dispatch(tenant_id=tenant_id, request_id=request_id)
    worker.coordinate_file_change_execution.apply_async.assert_not_called()


@pytest.mark.parametrize(
    "task_name,method_name,success_status",
    [
        ("purge_file_change_delete", "purge_delete", "purged"),
        ("cleanup_file_change_mutation", "continue_post_cutover_cleanup", "cleaned"),
        ("continue_file_change_compensation", "continue_compensation", "compensated"),
    ],
)
def test_delete_cleanup_and_compensation_propagate_owner_failure(
    worker,
    monkeypatch,
    task_name: str,
    method_name: str,
    success_status: str,
):
    _run_coroutine(monkeypatch, worker)
    method = AsyncMock(side_effect=[True, False])
    monkeypatch.setattr(worker, "_build_mutation_executor", lambda: SimpleNamespace(**{method_name: method}))
    task = getattr(worker, task_name)
    kwargs = {"request_id": 41, "execution_token": "generation-1"}

    assert task(SimpleNamespace(request=_task_request()), **kwargs) == {"status": success_status}
    with pytest.raises(RuntimeError, match="not verified"):
        task(SimpleNamespace(request=_task_request()), **kwargs)


def test_stage_delete_and_compensation_paths_only_delegate_to_knowledge_services():
    assert _WORKER_PATH.exists(), "T049 must create the Knowledge-owned F046 worker module"
    source = _WORKER_PATH.read_text(encoding="utf-8")
    required = (
        "_build_execution_coordinator",
        "_build_mutation_executor",
        "_build_compensation_service",
        "_build_file_change_service",
        "_build_upload_stage_service",
    )
    for fragment in required:
        assert fragment in source
    assert "approval" not in source.lower()
