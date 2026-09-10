"""Celery's request stack must be read on the calling worker thread."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from threading import local
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.worker.dsh.operations import register_operation_tasks
from bisheng.worker.dsh.reconciliation import register_reconciliation_tasks
from bisheng.worker.dsh.usage import register_usage_tasks


class ThreadLocalTaskApp:
    """Match Celery request visibility without the suite's globally mocked Celery import."""

    def task(self, **options):
        def decorate(function):
            class Task:
                def __init__(self):
                    self.state = local()

                @property
                def request(self):
                    return getattr(self.state, "request", SimpleNamespace(headers=None))

                def run(self, *args):
                    return function(self, *args) if options.get("bind") else function(*args)

            return Task()

        return decorate


def across_thread(factory):
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(factory())).result()


@pytest.mark.parametrize("kind", ["operation", "usage", "reconciliation", "inspection"])
@pytest.mark.parametrize("headers", [{"tenant_id": 1}, {}, {"tenant_id": 2}, {"tenant_id": "1"}, {"tenant_id": True}])
def test_request_tenant_survives_async_thread_bridge(monkeypatch, kind, headers):
    from bisheng.dsh import operations_runtime
    from bisheng.worker import _asyncio_utils
    from bisheng.worker.dsh.registry import register_dsh_tasks

    resume = AsyncMock(return_value=7)
    drain = AsyncMock(return_value=(7, False))
    inspect = AsyncMock(return_value=(0, 7))

    @contextmanager
    def repository_scope():
        yield SimpleNamespace(get=lambda _: SimpleNamespace(action="UPDATE_POLICY"))

    runtime = SimpleNamespace(
        policy=SimpleNamespace(resume=resume),
        reconciliation=SimpleNamespace(resume=resume),
        repository_scope=repository_scope,
        drain_user=drain,
        inspect_running=inspect,
        cleanup_batch=AsyncMock(),
    )

    @asynccontextmanager
    async def factory():
        yield runtime

    monkeypatch.setattr(_asyncio_utils, "run_async_task", across_thread)
    monkeypatch.setattr(operations_runtime, "projection_worker_runtime", factory)
    app = ThreadLocalTaskApp()
    if kind == "operation":
        task, _ = register_operation_tasks(app, factory, AsyncMock(return_value=[1]), lambda: None)
    elif kind == "usage":
        task = register_usage_tasks(app, factory)
    elif kind == "reconciliation":
        task = register_reconciliation_tasks(app, factory)
    else:
        task = register_dsh_tasks(app)["inspect"]
    task.state.request = SimpleNamespace(headers=headers)
    argument = 1 if kind in {"usage", "inspection"} else "operation-id"
    if type(headers.get("tenant_id")) is int and headers["tenant_id"] == 1:
        assert task.run(1, argument) == 7
    else:
        with pytest.raises(ValueError, match="tenant header"):
            task.run(1, argument)
        resume.assert_not_awaited()
        drain.assert_not_awaited()
        inspect.assert_not_awaited()
