from __future__ import annotations

# ruff: noqa: E402, I001 -- import order is intentionally controlled by fake Celery modules.

import importlib.util
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

for mod in ("celery", "celery.signals", "celery.schedules", "celery.app", "celery.app.task"):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()
from test.fixtures.mock_services import premock_import_chain

premock_import_chain()


class _FakeCelery:
    def task(self, *args, **kwargs):
        def _decorator(func):
            return func

        return _decorator


fake_worker_pkg = types.ModuleType("bisheng.worker")
fake_worker_pkg.__path__ = []  # type: ignore[attr-defined]
sys.modules["bisheng.worker"] = fake_worker_pkg

fake_worker_main = types.ModuleType("bisheng.worker.main")
fake_worker_main.bisheng_celery = _FakeCelery()
sys.modules["bisheng.worker.main"] = fake_worker_main

fake_asyncio_utils = types.ModuleType("bisheng.worker._asyncio_utils")
fake_asyncio_utils.run_async_task = MagicMock()
sys.modules["bisheng.worker._asyncio_utils"] = fake_asyncio_utils

from bisheng.approval.domain.models.approval_instance import (
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
)
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.approval_outbox_service import (
    ApprovalOutboxService,
    Completed,
    Deferred,
)
from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id

_TASKS_PATH = Path(__file__).resolve().parents[2] / "bisheng" / "worker" / "approval" / "tasks.py"
_TASKS_SPEC = importlib.util.spec_from_file_location("approval_worker_deferred_test_module", _TASKS_PATH)
assert _TASKS_SPEC and _TASKS_SPEC.loader
_TASKS_MODULE = importlib.util.module_from_spec(_TASKS_SPEC)
_TASKS_SPEC.loader.exec_module(_TASKS_MODULE)


def _outbox(*, status: ApprovalOutboxStatus = ApprovalOutboxStatus.PENDING) -> ApprovalOutbox:
    return ApprovalOutbox(
        id=11,
        tenant_id=23,
        instance_id=31,
        handler_key="knowledge_space_file_change",
        status=status,
        payload_snapshot={"request_id": 41},
    )


def _instance() -> ApprovalInstance:
    return ApprovalInstance(
        id=31,
        tenant_id=23,
        scenario_code="knowledge_space_file_change",
        scenario_name="知识空间文件变更",
        handler_key="knowledge_space_file_change",
        business_key="file-change:41",
        business_resource_type="knowledge_file",
        business_resource_id="51",
        business_name="report.pdf",
        applicant_user_id=61,
        applicant_user_name="alice",
        status=ApprovalInstanceStatus.APPROVED,
        payload_snapshot={"request_id": 41},
        detail_snapshot={"operation": "upload"},
    )


@pytest.mark.parametrize("task_name", ["execute_approval_outbox", "retry_approval_outbox"])
def test_task_restores_tenant_from_header_and_resets_context(monkeypatch: pytest.MonkeyPatch, task_name: str):
    observed: list[int | None] = []

    def fake_run_async_task(coro_factory):
        observed.append(get_current_tenant_id())
        coroutine = coro_factory()
        coroutine.close()
        return True

    monkeypatch.setattr(_TASKS_MODULE, "run_async_task", fake_run_async_task)
    outer_token = set_current_tenant_id(99)
    try:
        task = getattr(_TASKS_MODULE, task_name)
        assert task(SimpleNamespace(request=SimpleNamespace(headers={"tenant_id": "23"})), 11) is True
        assert observed == [23]
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(outer_token)


@pytest.mark.parametrize("headers", [None, {}, {"tenant_id": None}, {"tenant_id": "bad"}, {"tenant_id": 0}])
def test_task_missing_or_invalid_tenant_header_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict | None,
):
    run_async_task = MagicMock()
    monkeypatch.setattr(_TASKS_MODULE, "run_async_task", run_async_task)
    outer_token = set_current_tenant_id(99)
    try:
        with pytest.raises(ValueError, match="tenant_id header"):
            _TASKS_MODULE.execute_approval_outbox(SimpleNamespace(request=SimpleNamespace(headers=headers)), 11)

        run_async_task.assert_not_called()
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(outer_token)


@pytest.mark.asyncio
async def test_worker_preserves_completed_and_deferred_handler_results(monkeypatch: pytest.MonkeyPatch):
    outbox = _outbox()
    instance = _instance()
    deadline = datetime.utcnow() + timedelta(hours=1)
    results = [Completed(), Deferred("generation-1", deadline)]
    observed: list[Completed | Deferred] = []

    monkeypatch.setattr(ApprovalInstanceRepository, "get_outbox", AsyncMock(return_value=outbox))
    monkeypatch.setattr(ApprovalInstanceRepository, "get_instance", AsyncMock(return_value=instance))

    async def fake_execute(_self, *, outbox_id: int, executor):
        assert outbox_id == 11
        result = await executor(outbox)
        observed.append(result)
        return not isinstance(result, Deferred)

    monkeypatch.setattr(ApprovalOutboxService, "execute_outbox", fake_execute)

    for expected in results:
        handler = SimpleNamespace(on_approved=AsyncMock(return_value=expected))
        monkeypatch.setattr(_TASKS_MODULE, "build_runtime_handler", AsyncMock(return_value=handler))
        await _TASKS_MODULE._execute_approval_outbox_async(11)

    assert observed == results


@pytest.mark.asyncio
async def test_worker_deferred_result_persists_through_service_without_finalizing(
    monkeypatch: pytest.MonkeyPatch,
):
    outbox = _outbox()
    instance = _instance()
    result = Deferred("generation-1", datetime.utcnow() + timedelta(hours=1))
    handler = SimpleNamespace(on_approved=AsyncMock(return_value=result))
    claim = AsyncMock(return_value=outbox)
    defer = AsyncMock(return_value=True)
    finalize = AsyncMock()

    monkeypatch.setattr(ApprovalInstanceRepository, "get_outbox", AsyncMock(return_value=outbox))
    monkeypatch.setattr(ApprovalInstanceRepository, "get_instance", AsyncMock(return_value=instance))
    monkeypatch.setattr(ApprovalInstanceRepository, "finalize_outbox_success", finalize)
    monkeypatch.setattr(_TASKS_MODULE, "build_runtime_handler", AsyncMock(return_value=handler))
    monkeypatch.setattr(ApprovalOutboxService, "claim_outbox", claim)
    monkeypatch.setattr(ApprovalOutboxService, "defer_execution", defer)

    assert await _TASKS_MODULE._execute_approval_outbox_async(11) is True
    claim.assert_awaited_once()
    defer.assert_awaited_once_with(
        tenant_id=23,
        instance_id=31,
        outbox_id=11,
        result=result,
    )
    finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_initial_deferred_commit_dispatches_coordinator_once(monkeypatch: pytest.MonkeyPatch):
    outbox = _outbox()
    instance = _instance()
    dispatch = AsyncMock()
    handler = SimpleNamespace(
        on_approved=AsyncMock(return_value=Deferred("generation-1", datetime.utcnow() + timedelta(hours=1))),
        dispatch_deferred_execution=dispatch,
    )

    async def persist_deferred(_self, *, outbox_id: int, executor):
        result = await executor(outbox)
        assert isinstance(result, Deferred)
        outbox.status = ApprovalOutboxStatus.DEFERRED
        outbox.execution_token = result.execution_token
        return True

    monkeypatch.setattr(ApprovalInstanceRepository, "get_outbox", AsyncMock(return_value=outbox))
    monkeypatch.setattr(ApprovalInstanceRepository, "get_instance", AsyncMock(return_value=instance))
    monkeypatch.setattr(_TASKS_MODULE, "build_runtime_handler", AsyncMock(return_value=handler))
    monkeypatch.setattr(ApprovalOutboxService, "execute_outbox", persist_deferred)

    assert await _TASKS_MODULE._execute_approval_outbox_async(11) is True
    dispatch.assert_awaited_once_with(
        outbox_id=11,
        execution_token="generation-1",
        tenant_id=23,
    )


@pytest.mark.asyncio
async def test_completed_or_uncommitted_deferred_does_not_dispatch(monkeypatch: pytest.MonkeyPatch):
    outbox = _outbox()
    instance = _instance()
    dispatch = AsyncMock()
    handler = SimpleNamespace(on_approved=AsyncMock(return_value=Completed()), dispatch_deferred_execution=dispatch)
    execute = AsyncMock(return_value=True)

    monkeypatch.setattr(ApprovalInstanceRepository, "get_outbox", AsyncMock(return_value=outbox))
    monkeypatch.setattr(ApprovalInstanceRepository, "get_instance", AsyncMock(return_value=instance))
    monkeypatch.setattr(_TASKS_MODULE, "build_runtime_handler", AsyncMock(return_value=handler))
    monkeypatch.setattr(ApprovalOutboxService, "execute_outbox", execute)

    assert await _TASKS_MODULE._execute_approval_outbox_async(11) is True
    dispatch.assert_not_awaited()

    handler.on_approved.return_value = Deferred("generation-1", datetime.utcnow() + timedelta(hours=1))
    execute.return_value = False
    assert await _TASKS_MODULE._execute_approval_outbox_async(11) is False
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_deferred_dispatch_failure_retries_dispatch_without_reclaim(monkeypatch: pytest.MonkeyPatch):
    outbox = _outbox()
    instance = _instance()
    dispatch = AsyncMock(side_effect=[RuntimeError("broker unavailable"), None])
    handler = SimpleNamespace(
        on_approved=AsyncMock(return_value=Deferred("generation-1", datetime.utcnow() + timedelta(hours=1))),
        dispatch_deferred_execution=dispatch,
    )
    execute_calls = 0
    record_failure = AsyncMock()

    async def persist_deferred(_self, *, outbox_id: int, executor):
        nonlocal execute_calls
        execute_calls += 1
        result = await executor(outbox)
        outbox.status = ApprovalOutboxStatus.DEFERRED
        outbox.execution_token = result.execution_token
        return True

    monkeypatch.setattr(ApprovalInstanceRepository, "get_outbox", AsyncMock(return_value=outbox))
    monkeypatch.setattr(ApprovalInstanceRepository, "get_instance", AsyncMock(return_value=instance))
    monkeypatch.setattr(_TASKS_MODULE, "build_runtime_handler", AsyncMock(return_value=handler))
    monkeypatch.setattr(_TASKS_MODULE, "_record_outbox_task_failure", record_failure)
    monkeypatch.setattr(ApprovalOutboxService, "execute_outbox", persist_deferred)

    with pytest.raises(RuntimeError, match="dispatch"):
        await _TASKS_MODULE._execute_approval_outbox_async(11)
    assert outbox.status == ApprovalOutboxStatus.DEFERRED
    record_failure.assert_not_awaited()

    assert await _TASKS_MODULE._execute_approval_outbox_async(11) is False
    assert execute_calls == 1
    assert dispatch.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_name", ["_execute_approval_outbox_async", "_retry_approval_outbox_async"])
async def test_deferred_origin_is_never_reclaimed_or_recorded_as_failure(
    monkeypatch: pytest.MonkeyPatch,
    worker_name: str,
):
    outbox = _outbox(status=ApprovalOutboxStatus.FAILED)
    outbox.execution_token = "generation-1"
    build_handler = AsyncMock(side_effect=RuntimeError("must not build deferred handler"))
    record_failure = AsyncMock()
    execute_service = AsyncMock()
    retry_service = AsyncMock()

    monkeypatch.setattr(ApprovalInstanceRepository, "get_outbox", AsyncMock(return_value=outbox))
    monkeypatch.setattr(_TASKS_MODULE, "build_runtime_handler", build_handler)
    monkeypatch.setattr(_TASKS_MODULE, "_record_outbox_task_failure", record_failure)
    monkeypatch.setattr(ApprovalOutboxService, "execute_outbox", execute_service)
    monkeypatch.setattr(ApprovalOutboxService, "retry_outbox", retry_service)

    assert await getattr(_TASKS_MODULE, worker_name)(11) is False
    build_handler.assert_not_awaited()
    execute_service.assert_not_awaited()
    retry_service.assert_not_awaited()
    record_failure.assert_not_awaited()


@pytest.mark.asyncio
async def test_executor_keeps_retryable_exception_semantics():
    from bisheng.approval.domain.services.resource_user_invite_scenario_handler import (
        ApprovalInviteRetryableExecutionError,
    )

    handler = SimpleNamespace(
        on_approved=AsyncMock(side_effect=ApprovalInviteRetryableExecutionError("retry")),
    )
    executor = _TASKS_MODULE._build_outbox_executor(handler=handler, instance_id=31)

    with pytest.raises(ApprovalInviteRetryableExecutionError, match="retry"):
        await executor(_outbox())
