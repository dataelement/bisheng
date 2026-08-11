from __future__ import annotations

# ruff: noqa: E402, I001 -- fake Celery modules must exist before importing the worker.

import importlib.util
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

_WORKER_PATH = Path(__file__).resolve().parents[2] / "bisheng" / "worker" / "approval" / "file_change_tasks.py"
_WORKER_SPEC = importlib.util.spec_from_file_location("file_change_execution_worker_test_module", _WORKER_PATH)
assert _WORKER_SPEC and _WORKER_SPEC.loader
_WORKER_MODULE = importlib.util.module_from_spec(_WORKER_SPEC)
_WORKER_SPEC.loader.exec_module(_WORKER_MODULE)


@pytest.fixture(autouse=True)
def reset_worker_state():
    token = current_tenant_id.set(None)
    for task in fake_celery.tasks.values():
        task.apply_async.reset_mock()
        task.apply_async.side_effect = None
    yield
    current_tenant_id.reset(token)


def _request(tenant_id: int = 23):
    return SimpleNamespace(headers={"tenant_id": tenant_id})


def _identity() -> ExecutionIdentity:
    return ExecutionIdentity(
        tenant_id=23,
        request_id=41,
        instance_id=51,
        outbox_id=61,
        execution_token="generation-1",
    )


def _run_coroutine(monkeypatch: pytest.MonkeyPatch):
    def run(coroutine_factory):
        import asyncio

        return asyncio.run(coroutine_factory())

    monkeypatch.setattr(_WORKER_MODULE, "run_async_task", run)


def test_execution_workers_use_default_queue_and_exponential_backoff():
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
        "compensate_tenant_file_change_execution_steps",
        "cleanup_tenant_file_change_residue",
    }
    assert expected.issubset(fake_celery.tasks)
    for name in expected:
        options = fake_celery.tasks[name].options
        assert options["bind"] is True
        assert options["acks_late"] is True
        assert options["autoretry_for"] == (Exception,)
        assert options["retry_backoff"] is True
        assert options["retry_jitter"] is True
        assert options["retry_kwargs"]["max_retries"] > 0
        assert "queue" not in options

    for name in {
        "watchdog_all_file_change_executions",
        "compensate_all_file_change_execution_steps",
        "cleanup_all_file_change_residue",
    }:
        options = fake_celery.tasks[name].options
        assert options["acks_late"] is True
        assert options["autoretry_for"] == (Exception,)
        assert "queue" not in options


@pytest.mark.parametrize(
    "task_name,kwargs",
    [
        (
            "coordinate_file_change_execution",
            {"outbox_id": 61, "execution_token": "generation-1"},
        ),
        (
            "watchdog_file_change_execution",
            {"outbox_id": 61, "execution_token": "generation-1"},
        ),
        (
            "cleanup_file_change_upload_stage",
            {"request_id": 41, "upload_id": "opaque-1", "terminal_action": "rejected"},
        ),
        (
            "purge_file_change_delete",
            {"request_id": 41, "execution_token": "generation-1"},
        ),
        (
            "cleanup_file_change_mutation",
            {"request_id": 41, "execution_token": "generation-1"},
        ),
    ],
)
def test_execution_worker_restores_tenant_header_context(
    monkeypatch: pytest.MonkeyPatch,
    task_name: str,
    kwargs: dict,
):
    observed: list[int | None] = []

    def fake_run(coroutine_factory):
        observed.append(get_current_tenant_id())
        coroutine = coroutine_factory()
        coroutine.close()
        return {"status": "ok"}

    monkeypatch.setattr(_WORKER_MODULE, "run_async_task", fake_run)
    outer = set_current_tenant_id(99)
    try:
        task = getattr(_WORKER_MODULE, task_name)
        assert task(SimpleNamespace(request=_request()), **kwargs) == {"status": "ok"}
        assert observed == [23]
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(outer)


@pytest.mark.parametrize("headers", [None, {}, {"tenant_id": None}, {"tenant_id": "bad"}, {"tenant_id": 0}])
def test_execution_worker_fails_closed_without_positive_tenant_header(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict | None,
):
    run = MagicMock()
    monkeypatch.setattr(_WORKER_MODULE, "run_async_task", run)

    with pytest.raises(ValueError, match="tenant_id header"):
        _WORKER_MODULE.coordinate_file_change_execution(
            SimpleNamespace(request=SimpleNamespace(headers=headers)),
            outbox_id=61,
            execution_token="generation-1",
        )
    run.assert_not_called()


def test_coordinate_worker_binds_outbox_and_token_then_dispatches(monkeypatch: pytest.MonkeyPatch):
    _run_coroutine(monkeypatch)
    coordinator = SimpleNamespace(coordinate_outbox_execution=AsyncMock(return_value=ExecutionReconcileStatus.RUNNING))
    monkeypatch.setattr(_WORKER_MODULE, "_build_execution_coordinator", lambda: coordinator)

    result = _WORKER_MODULE.coordinate_file_change_execution(
        SimpleNamespace(request=_request()),
        outbox_id=61,
        execution_token="generation-1",
    )

    assert result == {"status": "running"}
    coordinator.coordinate_outbox_execution.assert_awaited_once_with(
        tenant_id=23,
        outbox_id=61,
        execution_token="generation-1",
        dispatcher=_WORKER_MODULE._dispatch_file_change_step,
    )


async def test_step_dispatch_uses_stable_key_and_explicit_tenant_header():
    context = ExecutionStepContext(
        tenant_id=23,
        request_id=41,
        instance_id=51,
        outbox_id=61,
        execution_token="generation-1",
        action="rename",
        step_code="rename.index_shadow",
        idempotency_key="f046:41:rename.index_shadow",
        task_id=None,
    )

    task_id = await _WORKER_MODULE._dispatch_file_change_step(context)

    call = _WORKER_MODULE.execute_file_change_step.apply_async.call_args
    assert call.kwargs["task_id"] == "f046:41:rename.index_shadow"
    assert call.kwargs["headers"] == {"tenant_id": 23}
    assert call.kwargs["kwargs"]["execution_token"] == "generation-1"
    assert call.kwargs["kwargs"]["step_code"] == "rename.index_shadow"
    assert task_id == "f046:41:rename.index_shadow"


def test_watchdog_only_fails_the_current_deferred_generation(monkeypatch: pytest.MonkeyPatch):
    _run_coroutine(monkeypatch)
    coordinator = SimpleNamespace(
        load_identity=AsyncMock(side_effect=[None, _identity()]),
        fail=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(_WORKER_MODULE, "_build_execution_coordinator", lambda: coordinator)

    stale = _WORKER_MODULE.watchdog_file_change_execution(
        SimpleNamespace(request=_request()),
        outbox_id=61,
        execution_token="old-generation",
    )
    current = _WORKER_MODULE.watchdog_file_change_execution(
        SimpleNamespace(request=_request()),
        outbox_id=61,
        execution_token="generation-1",
        heartbeat_timeout_seconds=900,
    )

    assert stale == {"status": "ignored"}
    assert current == {"status": "failed"}
    coordinator.fail.assert_awaited_once_with(
        identity=_identity(),
        error_summary="deferred execution watchdog timeout",
        watchdog=True,
        heartbeat_timeout_seconds=900,
    )


def test_stage_cleanup_is_idempotent_service_call_and_failure_is_retried(monkeypatch: pytest.MonkeyPatch):
    _run_coroutine(monkeypatch)
    handler = SimpleNamespace(terminal_cleanup=AsyncMock(return_value={"cleanup_state": "success"}))
    monkeypatch.setattr(_WORKER_MODULE, "build_runtime_handler", AsyncMock(return_value=handler))

    first = _WORKER_MODULE.cleanup_file_change_upload_stage(
        SimpleNamespace(request=_request()),
        request_id=41,
        upload_id="opaque-1",
        terminal_action="rejected",
    )
    second = _WORKER_MODULE.cleanup_file_change_upload_stage(
        SimpleNamespace(request=_request()),
        request_id=41,
        upload_id="opaque-1",
        terminal_action="rejected",
    )

    assert first == second == {"cleanup_state": "success"}
    assert handler.terminal_cleanup.await_count == 2

    handler.terminal_cleanup.side_effect = RuntimeError("object store unavailable")
    with pytest.raises(RuntimeError, match="object store unavailable"):
        _WORKER_MODULE.cleanup_file_change_upload_stage(
            SimpleNamespace(request=_request()),
            request_id=41,
            upload_id="opaque-1",
            terminal_action="rejected",
        )


def test_delete_purge_requires_verified_owner_service_success(monkeypatch: pytest.MonkeyPatch):
    _run_coroutine(monkeypatch)
    executor = SimpleNamespace(purge_delete=AsyncMock(side_effect=[True, False]))
    monkeypatch.setattr(_WORKER_MODULE, "_build_mutation_executor", lambda: executor)

    assert _WORKER_MODULE.purge_file_change_delete(
        SimpleNamespace(request=_request()),
        request_id=41,
        execution_token="generation-1",
    ) == {"status": "purged"}

    with pytest.raises(RuntimeError, match="not verified"):
        _WORKER_MODULE.purge_file_change_delete(
            SimpleNamespace(request=_request()),
            request_id=41,
            execution_token="generation-1",
        )


def test_upload_pipeline_callback_forwards_stable_request_token_to_coordinator(
    monkeypatch: pytest.MonkeyPatch,
):
    _run_coroutine(monkeypatch)
    coordinator = SimpleNamespace(
        acknowledge_upload_terminal=AsyncMock(return_value=ExecutionReconcileStatus.COMPLETED)
    )
    monkeypatch.setattr(_WORKER_MODULE, "_build_execution_coordinator", lambda: coordinator)

    result = _WORKER_MODULE.acknowledge_file_change_upload_pipeline(
        SimpleNamespace(request=_request()),
        request_id=41,
        execution_token="generation-1",
        file_id=71,
    )

    assert result == {"status": "completed"}
    coordinator.acknowledge_upload_terminal.assert_awaited_once_with(
        tenant_id=23,
        request_id=41,
        execution_token="generation-1",
        file_id=71,
    )


def test_execution_step_worker_acknowledges_only_owner_verified_result(monkeypatch: pytest.MonkeyPatch):
    _run_coroutine(monkeypatch)
    coordinator = SimpleNamespace(
        load_identity=AsyncMock(return_value=_identity()),
        acknowledge_step=AsyncMock(return_value=ExecutionReconcileStatus.COMPLETED),
    )
    executor = SimpleNamespace(execute_and_verify_step=AsyncMock())
    monkeypatch.setattr(_WORKER_MODULE, "_build_execution_coordinator", lambda: coordinator)
    monkeypatch.setattr(_WORKER_MODULE, "_build_mutation_executor", lambda: executor)

    result = _WORKER_MODULE.execute_file_change_step(
        SimpleNamespace(request=_request()),
        request_id=41,
        instance_id=51,
        outbox_id=61,
        execution_token="generation-1",
        action="rename",
        step_code="rename.index_shadow",
        idempotency_key="f046:41:rename.index_shadow",
    )

    assert result == {"status": "completed"}
    coordinator.load_identity.assert_awaited_once_with(
        tenant_id=23,
        outbox_id=61,
        execution_token="generation-1",
    )
    coordinator.acknowledge_step.assert_awaited_once_with(
        identity=_identity(),
        step_code="rename.index_shadow",
        verifier=executor.execute_and_verify_step,
    )
    executor.execute_and_verify_step.assert_not_awaited()


def test_execution_step_worker_ignores_stale_generation_before_owner_execution(monkeypatch: pytest.MonkeyPatch):
    _run_coroutine(monkeypatch)
    coordinator = SimpleNamespace(load_identity=AsyncMock(return_value=None))
    build_executor = MagicMock()
    monkeypatch.setattr(_WORKER_MODULE, "_build_execution_coordinator", lambda: coordinator)
    monkeypatch.setattr(_WORKER_MODULE, "_build_mutation_executor", build_executor)

    result = _WORKER_MODULE.execute_file_change_step(
        SimpleNamespace(request=_request()),
        request_id=41,
        instance_id=51,
        outbox_id=61,
        execution_token="generation-stale",
        action="rename",
        step_code="rename.index_shadow",
        idempotency_key="f046:41:rename.index_shadow",
    )

    assert result == {"status": "ignored"}
    build_executor.assert_not_called()


async def test_watchdog_beat_page_dispatches_token_bound_work_and_keyset_continuation(
    monkeypatch: pytest.MonkeyPatch,
):
    page = SimpleNamespace(
        items=[SimpleNamespace(outbox_id=61, request_id=41, execution_token="generation-1")],
        has_more=True,
        next_after_id=61,
    )
    service = SimpleNamespace(list_deferred_watchdog_page=AsyncMock(return_value=page))
    monkeypatch.setattr(_WORKER_MODULE, "_build_compensation_service", lambda: service)

    result = await _WORKER_MODULE._watchdog_tenant_page_async(tenant_id=23, after_outbox_id=0)

    assert result == {"processed": 1, "dispatched": 1, "failed": 0, "has_more": True}
    service.list_deferred_watchdog_page.assert_awaited_once_with(
        tenant_id=23,
        scenario_code="knowledge_space_file_change_request",
        after_outbox_id=0,
        limit=_WORKER_MODULE.COMPENSATION_BATCH_SIZE,
    )
    _WORKER_MODULE.watchdog_file_change_execution.apply_async.assert_called_once_with(
        kwargs={"outbox_id": 61, "execution_token": "generation-1"},
        headers={"tenant_id": 23},
    )
    _WORKER_MODULE.watchdog_tenant_file_change_executions.apply_async.assert_called_once_with(
        kwargs={"after_outbox_id": 61},
        headers={"tenant_id": 23},
    )


async def test_step_beat_page_routes_applying_and_compensating_generations_to_owner_paths(
    monkeypatch: pytest.MonkeyPatch,
):
    page = SimpleNamespace(
        items=[
            SimpleNamespace(
                step_id=301,
                request_id=41,
                instance_id=51,
                outbox_id=61,
                execution_token="generation-1",
                execution_state="applying",
            ),
            # A second due step for the same generation must not enqueue a
            # duplicate coordinator in the same page.
            SimpleNamespace(
                step_id=302,
                request_id=41,
                instance_id=51,
                outbox_id=61,
                execution_token="generation-1",
                execution_state="applying",
            ),
            SimpleNamespace(
                step_id=303,
                request_id=42,
                instance_id=52,
                outbox_id=62,
                execution_token="generation-2",
                execution_state="compensating",
            ),
        ],
        has_more=False,
        next_after_id=303,
    )
    service = SimpleNamespace(list_step_recovery_page=AsyncMock(return_value=page))
    monkeypatch.setattr(_WORKER_MODULE, "_build_compensation_service", lambda: service)

    result = await _WORKER_MODULE._compensate_tenant_step_page_async(tenant_id=23, after_step_id=0)

    assert result == {"processed": 3, "dispatched": 2, "failed": 0, "has_more": False}
    _WORKER_MODULE.coordinate_file_change_execution.apply_async.assert_called_once_with(
        kwargs={"outbox_id": 61, "execution_token": "generation-1"},
        headers={"tenant_id": 23},
    )
    _WORKER_MODULE.continue_file_change_compensation.apply_async.assert_called_once_with(
        kwargs={"request_id": 42, "execution_token": "generation-2"},
        headers={"tenant_id": 23},
    )


async def test_cleanup_beat_page_dispatches_stage_and_delete_without_fake_success(
    monkeypatch: pytest.MonkeyPatch,
):
    page = SimpleNamespace(
        items=[
            SimpleNamespace(
                request_id=71,
                kind="stage",
                upload_id="opaque-1",
                terminal_action="rejected",
                execution_token=None,
            ),
            SimpleNamespace(
                request_id=72,
                kind="delete_purge",
                upload_id=None,
                terminal_action=None,
                execution_token="delete-generation",
            ),
            SimpleNamespace(
                request_id=73,
                kind="mutation_cleanup",
                upload_id=None,
                terminal_action=None,
                execution_token="mutation-generation",
            ),
        ],
        has_more=True,
        next_after_id=73,
    )
    stage_page = SimpleNamespace(
        items=[SimpleNamespace(stage_id=81, upload_id="lifecycle-1")],
        has_more=True,
        next_after_id=81,
    )
    service = SimpleNamespace(
        list_cleanup_page=AsyncMock(return_value=page),
        list_expired_orphan_stage_page=AsyncMock(return_value=stage_page),
    )
    monkeypatch.setattr(_WORKER_MODULE, "_build_compensation_service", lambda: service)

    result = await _WORKER_MODULE._cleanup_tenant_page_async(
        tenant_id=23,
        after_request_id=0,
        after_stage_id=0,
    )

    assert result == {"processed": 4, "dispatched": 4, "failed": 0, "has_more": True}
    _WORKER_MODULE.cleanup_file_change_upload_stage.apply_async.assert_called_once_with(
        kwargs={"request_id": 71, "upload_id": "opaque-1", "terminal_action": "rejected"},
        headers={"tenant_id": 23},
    )
    _WORKER_MODULE.purge_file_change_delete.apply_async.assert_called_once_with(
        kwargs={"request_id": 72, "execution_token": "delete-generation"},
        headers={"tenant_id": 23},
    )
    _WORKER_MODULE.cleanup_file_change_mutation.apply_async.assert_called_once_with(
        kwargs={"request_id": 73, "execution_token": "mutation-generation"},
        headers={"tenant_id": 23},
    )
    _WORKER_MODULE.cleanup_orphan_file_change_upload_stage.apply_async.assert_called_once_with(
        kwargs={"upload_id": "lifecycle-1"},
        headers={"tenant_id": 23},
    )
    _WORKER_MODULE.cleanup_tenant_file_change_residue.apply_async.assert_called_once_with(
        kwargs={"after_request_id": 73, "after_stage_id": 81},
        headers={"tenant_id": 23},
    )


async def test_cleanup_beat_resumes_after_empty_filtered_request_page(monkeypatch: pytest.MonkeyPatch):
    page = SimpleNamespace(items=[], has_more=True, next_after_id=140)
    stage_page = SimpleNamespace(items=[], has_more=False, next_after_id=80)
    service = SimpleNamespace(
        list_cleanup_page=AsyncMock(return_value=page),
        list_expired_orphan_stage_page=AsyncMock(return_value=stage_page),
    )
    monkeypatch.setattr(_WORKER_MODULE, "_build_compensation_service", lambda: service)

    result = await _WORKER_MODULE._cleanup_tenant_page_async(
        tenant_id=23,
        after_request_id=0,
        after_stage_id=80,
    )

    assert result == {"processed": 0, "dispatched": 0, "failed": 0, "has_more": True}
    _WORKER_MODULE.cleanup_tenant_file_change_residue.apply_async.assert_called_once_with(
        kwargs={"after_request_id": 140, "after_stage_id": 80},
        headers={"tenant_id": 23},
    )


def test_orphan_cleanup_worker_uses_race_safe_owner_service(monkeypatch: pytest.MonkeyPatch):
    _run_coroutine(monkeypatch)
    service = SimpleNamespace(reconcile_lifecycle=AsyncMock(side_effect=[True, False]))
    monkeypatch.setattr(_WORKER_MODULE, "_build_upload_stage_service", AsyncMock(return_value=service))

    cleaned = _WORKER_MODULE.cleanup_orphan_file_change_upload_stage(
        SimpleNamespace(request=_request()),
        upload_id="expired-orphan",
    )
    stale = _WORKER_MODULE.cleanup_orphan_file_change_upload_stage(
        SimpleNamespace(request=_request()),
        upload_id="now-attached",
    )

    assert cleaned == {"status": "reconciled"}
    assert stale == {"status": "ignored"}


def test_compensation_worker_calls_only_owner_token_bound_interface(monkeypatch: pytest.MonkeyPatch):
    _run_coroutine(monkeypatch)
    executor = SimpleNamespace(continue_compensation=AsyncMock(side_effect=[True, False]))
    monkeypatch.setattr(_WORKER_MODULE, "_build_mutation_executor", lambda: executor)

    completed = _WORKER_MODULE.continue_file_change_compensation(
        SimpleNamespace(request=_request()),
        request_id=41,
        execution_token="generation-1",
    )
    stale = _WORKER_MODULE.continue_file_change_compensation(
        SimpleNamespace(request=_request()),
        request_id=41,
        execution_token="old-generation",
    )

    assert completed == {"status": "compensated"}
    assert stale == {"status": "ignored"}
    assert executor.continue_compensation.await_args_list[0].kwargs == {
        "request_id": 41,
        "execution_token": "generation-1",
    }


async def test_maintenance_coordinator_enumerates_once_and_isolates_tenant_dispatch_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(_WORKER_MODULE, "_load_active_tenant_ids", AsyncMock(return_value=[11, 12, 13]))
    task = SimpleNamespace(apply_async=MagicMock())
    task.apply_async.side_effect = [None, RuntimeError("broker unavailable"), None]

    result = await _WORKER_MODULE._coordinate_maintenance_all_tenants_async(
        tenant_task=task,
        initial_kwargs={"after_step_id": 0},
        operation="execution_recovery",
    )

    assert result == {"tenant_count": 3, "dispatched": 2, "failed": 1}
    assert [call.kwargs["headers"] for call in task.apply_async.call_args_list] == [
        {"tenant_id": 11},
        {"tenant_id": 12},
        {"tenant_id": 13},
    ]
