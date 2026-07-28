from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.core.config.settings import CeleryConf
from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
    DepartmentTransferCleanupEventStatus,
)


def _load_worker_module() -> tuple[ModuleType, dict[str, dict]]:
    task_options: dict[str, dict] = {}

    class CeleryStub:
        @staticmethod
        def task(*_args, **kwargs):
            def decorator(function):
                task_options[function.__name__] = kwargs
                function.apply_async = Mock()
                return function

            return decorator

    worker_root = Path(__file__).resolve().parents[2] / "bisheng" / "worker"
    worker_package = ModuleType("bisheng.worker")
    worker_package.__path__ = [str(worker_root)]
    sys.modules["bisheng.worker"] = worker_package

    permission_package = ModuleType("bisheng.worker.permission")
    permission_package.__path__ = [str(worker_root / "permission")]
    sys.modules["bisheng.worker.permission"] = permission_package
    sys.modules["bisheng.worker.main"] = SimpleNamespace(bisheng_celery=CeleryStub())

    module_path = worker_root / "permission" / "department_transfer_cleanup.py"
    spec = importlib.util.spec_from_file_location(
        "bisheng.worker.permission.department_transfer_cleanup",
        module_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, task_options


worker_module, worker_task_options = _load_worker_module()


class _SessionContext:
    def __init__(self):
        self.session = SimpleNamespace(commit=AsyncMock())

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return None


def test_tasks_are_late_acknowledged_and_permission_route_is_forced():
    assert worker_task_options["process_event"]["acks_late"] is True
    assert worker_task_options["scan_due_events"]["acks_late"] is True

    config = CeleryConf(
        task_routers={"custom.task": {"queue": "custom"}},
        beat_schedule={},
    )

    assert config.task_routers["bisheng.worker.permission.*"] == {"queue": "knowledge_celery"}
    scan = config.beat_schedule["scan_department_transfer_permission_cleanup"]
    assert scan["task"].endswith(".scan_due_events")
    assert scan["schedule"] == 30.0


@pytest.mark.asyncio
async def test_scan_recovers_preparing_event_and_dispatches_due_event(monkeypatch):
    event = SimpleNamespace(
        id=51,
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source="login_sync",
        status=DepartmentTransferCleanupEventStatus.PREPARING,
        deadline_at=None,
        retry_count=0,
        last_error=None,
    )
    repository = SimpleNamespace(
        list_preparing_events=AsyncMock(return_value=[event]),
        activate_event=AsyncMock(),
        list_due_event_ids=AsyncMock(return_value=[51]),
        find_by_id=AsyncMock(return_value=event),
        mark_event_overdue=AsyncMock(return_value=False),
    )
    session_context = _SessionContext()
    monkeypatch.setattr(
        worker_module,
        "get_async_db_session",
        lambda: session_context,
    )
    monkeypatch.setattr(
        worker_module,
        "DepartmentTransferPermissionCleanupRepositoryImpl",
        lambda _session: repository,
    )
    monkeypatch.setattr(
        worker_module,
        "_load_primary_department",
        AsyncMock(return_value=20),
    )
    worker_module.process_event.apply_async.reset_mock()

    dispatched = await worker_module._scan_due_events_async()

    assert dispatched == 1
    repository.activate_event.assert_awaited_once()
    worker_module.process_event.apply_async.assert_called_once_with(
        args=[51],
        queue="knowledge_celery",
    )


@pytest.mark.asyncio
async def test_overdue_logs_critical_only_on_first_transition(caplog):
    event = SimpleNamespace(
        id=52,
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source="local",
        status=DepartmentTransferCleanupEventStatus.FAILED,
        retry_count=3,
        last_error="projection_failed",
    )
    repository = SimpleNamespace(
        mark_event_overdue=AsyncMock(side_effect=[True, False]),
    )

    with caplog.at_level(logging.CRITICAL):
        assert (
            await worker_module._mark_overdue_if_needed(
                repository,
                event,
                now=worker_module.datetime.now(),
            )
            is True
        )
        assert (
            await worker_module._mark_overdue_if_needed(
                repository,
                event,
                now=worker_module.datetime.now(),
            )
            is False
        )

    critical_messages = [record.getMessage() for record in caplog.records if record.levelno == logging.CRITICAL]
    assert len(critical_messages) == 1
    assert "event_id=52" in critical_messages[0]
    assert "user_id=7" in critical_messages[0]
