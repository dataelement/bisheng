"""Exercise the Celery entry points, including the legacy inspection callback."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def registered_usage(monkeypatch):
    from bisheng.dsh import operations_runtime
    from bisheng.worker import _asyncio_utils
    from bisheng.worker.dsh import registry

    service = SimpleNamespace(inspect_running=AsyncMock(), cleanup_batch=AsyncMock())

    @asynccontextmanager
    async def runtime():
        yield service

    class App:
        def task(self, **options):
            def decorate(function):
                if options.get("bind"):
                    task = SimpleNamespace(request=SimpleNamespace(headers={"tenant_id": 2}))
                    task.run = lambda *args: function(task, *args)
                else:
                    task = SimpleNamespace(run=function)
                task.apply_async = Mock()
                return task

            return decorate

    for name in (
        "register_model_audit_tasks",
        "register_audit_tree_tasks",
        "register_content_safety_tasks",
        "register_operation_tasks",
        "register_usage_tasks",
    ):
        monkeypatch.setattr(registry, name, Mock())
    monkeypatch.setattr(operations_runtime, "projection_worker_runtime", runtime)
    monkeypatch.setattr(_asyncio_utils, "run_async_task", lambda factory: factory())
    return registry.register_dsh_tasks(App()), service


async def test_dispatch_entrypoint_consumes_bounded_work(registered_usage, monkeypatch):
    from bisheng.worker.dsh import registry

    tasks, service = registered_usage
    dispatch = AsyncMock(return_value=7)
    dispatcher = Mock(return_value=SimpleNamespace(dispatch=dispatch))
    monkeypatch.setattr(registry, "UsageDispatcher", dispatcher)

    assert await tasks["dispatch"].run() == 7
    dispatcher.assert_called_once_with(service)
    dispatch.assert_awaited_once_with()
    tasks["scan"].apply_async.assert_not_called()


@pytest.mark.parametrize("next_cursor", [0, 7])
async def test_legacy_inspection_schedules_only_remaining_page(registered_usage, next_cursor):
    tasks, service = registered_usage
    service.inspect_running.return_value = (next_cursor, 3)

    assert await tasks["inspect"].run(2, 20, 5) == 3
    assert service.inspect_running.await_args.kwargs["cursor"] == 5
    service.cleanup_batch.assert_awaited_once_with(2, 20)
    if next_cursor:
        tasks["inspect"].apply_async.assert_called_once_with(
            args=[2, 20, next_cursor], headers={"tenant_id": 2}, countdown=1
        )
    else:
        tasks["inspect"].apply_async.assert_not_called()
