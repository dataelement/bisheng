import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest

from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id


class _FakeTask:
    def __init__(self, function):
        self.run = function
        self.delay = Mock()


class _FakeCelery:
    def task(self, *args, **kwargs):
        def decorator(function):
            return _FakeTask(function)

        return decorator


fake_worker_main = types.ModuleType("bisheng.worker.main")
fake_worker_main.bisheng_celery = _FakeCelery()
sys.modules["bisheng.worker.main"] = fake_worker_main

fake_asyncio_utils = types.ModuleType("bisheng.worker._asyncio_utils")
fake_asyncio_utils.run_async_task = Mock()
sys.modules["bisheng.worker._asyncio_utils"] = fake_asyncio_utils

_TASKS_PATH = Path(__file__).resolve().parents[2] / "bisheng" / "worker" / "approval" / "notification_tasks.py"
_TASKS_SPEC = importlib.util.spec_from_file_location("approval_notification_worker_test_module", _TASKS_PATH)
assert _TASKS_SPEC and _TASKS_SPEC.loader
notification_tasks = importlib.util.module_from_spec(_TASKS_SPEC)
_TASKS_SPEC.loader.exec_module(notification_tasks)


@pytest.mark.asyncio
async def test_consumer_restores_previous_tenant_context(monkeypatch):
    service = SimpleNamespace(consume=AsyncMock(return_value=True))
    monkeypatch.setattr(
        notification_tasks,
        "_build_notification_service",
        AsyncMock(return_value=service),
    )
    token = set_current_tenant_id(99)
    try:
        result = await notification_tasks._consume_approval_notification_async(1, 7)
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(token)

    assert result is True
    service.consume.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_beat_dispatches_cross_tenant_rows_below_retry_limit(monkeypatch):
    rows = [
        SimpleNamespace(id=1, tenant_id=7),
        SimpleNamespace(id=2, tenant_id=8),
    ]
    monkeypatch.setattr(
        notification_tasks.ApprovalNotificationOutboxRepository,
        "list_dispatchable",
        AsyncMock(return_value=rows),
    )
    delay = Mock()
    monkeypatch.setattr(notification_tasks.consume_approval_notification, "delay", delay)

    count = await notification_tasks._dispatch_approval_notifications_async()

    assert count == 2
    assert delay.call_args_list == [call(1, 7), call(2, 8)]


def test_consumer_skips_when_distributed_lock_is_held(monkeypatch):
    redis = SimpleNamespace(setNx=Mock(return_value=False), delete=Mock())
    monkeypatch.setattr(notification_tasks, "_get_redis", Mock(return_value=redis))
    run_async_task = Mock()
    monkeypatch.setattr(notification_tasks, "run_async_task", run_async_task)

    result = notification_tasks.consume_approval_notification.run(1, 7)

    assert result is False
    run_async_task.assert_not_called()
    redis.delete.assert_not_called()
