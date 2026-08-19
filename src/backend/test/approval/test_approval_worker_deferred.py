from __future__ import annotations

# ruff: noqa: E402, I001 -- fake Celery modules must exist before loading the worker module.

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


class _FakeCelery:
    def task(self, *args, **kwargs):
        del args, kwargs

        def decorator(function):
            return function

        return decorator


fake_worker_package = types.ModuleType("bisheng.worker")
fake_worker_package.__path__ = []  # type: ignore[attr-defined]
sys.modules["bisheng.worker"] = fake_worker_package

fake_worker_main = types.ModuleType("bisheng.worker.main")
fake_worker_main.bisheng_celery = _FakeCelery()
sys.modules["bisheng.worker.main"] = fake_worker_main

fake_asyncio_utils = types.ModuleType("bisheng.worker._asyncio_utils")
fake_asyncio_utils.run_async_task = MagicMock()
sys.modules["bisheng.worker._asyncio_utils"] = fake_asyncio_utils

from bisheng.approval.domain.models.approval_instance import ApprovalOutbox, ApprovalOutboxStatus
from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APPROVAL_WORKER_ROOT = BACKEND_ROOT / "bisheng" / "worker" / "approval"
TASKS_PATH = APPROVAL_WORKER_ROOT / "tasks.py"
TASKS_SPEC = importlib.util.spec_from_file_location("approval_worker_contract_test_module", TASKS_PATH)
assert TASKS_SPEC and TASKS_SPEC.loader
TASKS_MODULE = importlib.util.module_from_spec(TASKS_SPEC)
TASKS_SPEC.loader.exec_module(TASKS_MODULE)

LEGACY_SCENARIOS = (
    "menu_access_request",
    "channel_subscribe_request",
    "knowledge_space_subscribe_request",
)


def _outbox(*, handler_key: str) -> ApprovalOutbox:
    return ApprovalOutbox(
        id=11,
        tenant_id=23,
        instance_id=31,
        handler_key=handler_key,
        status=ApprovalOutboxStatus.PENDING,
        payload_snapshot={"resource_id": "41"},
    )


@pytest.mark.parametrize("task_name", ["execute_approval_outbox", "retry_approval_outbox"])
def test_legacy_outbox_task_restores_explicit_tenant_header(
    monkeypatch: pytest.MonkeyPatch,
    task_name: str,
) -> None:
    observed: list[int | None] = []

    def run_async_task(coroutine_factory):
        observed.append(get_current_tenant_id())
        coroutine = coroutine_factory()
        coroutine.close()
        return True

    monkeypatch.setattr(TASKS_MODULE, "run_async_task", run_async_task)
    outer_token = set_current_tenant_id(99)
    try:
        task = getattr(TASKS_MODULE, task_name)
        assert task(SimpleNamespace(request=SimpleNamespace(headers={"tenant_id": "23"})), 11) is True
        assert observed == [23]
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(outer_token)


@pytest.mark.parametrize("headers", [None, {}, {"tenant_id": None}, {"tenant_id": "bad"}, {"tenant_id": 0}])
def test_legacy_outbox_task_fails_closed_without_positive_tenant_header(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict | None,
) -> None:
    run_async_task = MagicMock()
    monkeypatch.setattr(TASKS_MODULE, "run_async_task", run_async_task)

    with pytest.raises(ValueError, match="tenant_id header"):
        TASKS_MODULE.execute_approval_outbox(
            SimpleNamespace(request=SimpleNamespace(headers=headers)),
            11,
        )

    run_async_task.assert_not_called()


@pytest.mark.parametrize("scenario_code", LEGACY_SCENARIOS)
async def test_three_released_scenarios_keep_worker_handler_success_semantics(
    scenario_code: str,
) -> None:
    outbox = _outbox(handler_key=scenario_code)
    handler = SimpleNamespace(on_approved=AsyncMock(return_value={"status": "ok"}))

    executor = TASKS_MODULE._build_outbox_executor(handler=handler, instance_id=31)
    result = await executor(outbox)

    assert result == (True, None)
    handler.on_approved.assert_awaited_once_with(31, {"resource_id": "41"})


@pytest.mark.parametrize("scenario_code", LEGACY_SCENARIOS)
async def test_three_released_scenarios_keep_worker_handler_failure_semantics(
    scenario_code: str,
) -> None:
    outbox = _outbox(handler_key=scenario_code)
    handler = SimpleNamespace(on_approved=AsyncMock(side_effect=RuntimeError("controlled legacy failure")))

    executor = TASKS_MODULE._build_outbox_executor(handler=handler, instance_id=31)
    result = await executor(outbox)

    assert result == (False, "controlled legacy failure")
    handler.on_approved.assert_awaited_once_with(31, {"resource_id": "41"})


def test_approval_worker_package_has_no_f046_task_module_or_import() -> None:
    approval_package_source = (APPROVAL_WORKER_ROOT / "__init__.py").read_text(encoding="utf-8")
    worker_package_source = (BACKEND_ROOT / "bisheng" / "worker" / "__init__.py").read_text(encoding="utf-8")

    assert not (APPROVAL_WORKER_ROOT / "file_change_tasks.py").exists()
    assert "worker.approval.file_change_tasks" not in approval_package_source
    assert "worker.approval.file_change_tasks" not in worker_package_source


def test_legacy_approval_worker_has_no_deferred_or_f046_business_dispatch_path() -> None:
    source = inspect.getsource(TASKS_MODULE)
    forbidden_fragments = (
        "Deferred",
        "ApprovalDeferredDispatchError",
        "dispatch_deferred_execution",
        "_dispatch_committed_deferred",
        "execution_token",
        "knowledge_space_file_change",
    )

    used = [fragment for fragment in forbidden_fragments if fragment in source]
    assert used == [], f"legacy Approval worker still owns F045/F046 business execution: {used}"
