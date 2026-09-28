"""跨线程发布、取消和共享循环误用的行为契约。"""

import asyncio
import contextvars
import importlib.util
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path

import pytest

from bisheng.utils.task_dispatch import run_sync_dispatch


def load_bridge():
    path = Path(__file__).parents[2] / "bisheng/worker/_asyncio_utils.py"
    spec = importlib.util.spec_from_file_location("async_boundary_bridge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_slow_publish_yields_preserves_context_and_propagates_failure():
    tenant = contextvars.ContextVar("tenant_probe")
    tenant.set(17)
    loop_thread = threading.get_ident()
    release = threading.Event()
    started = threading.Event()
    observed = []

    def publish():
        observed.append((threading.get_ident(), tenant.get()))
        started.set()
        assert release.wait(2)
        raise LookupError("broker unavailable")

    task = asyncio.create_task(run_sync_dispatch(publish))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        assert not task.done()
        assert observed == [(observed[0][0], 17)]
        assert observed[0][0] != loop_thread
    finally:
        release.set()
    with pytest.raises(LookupError, match="broker unavailable"):
        await task


def test_bridge_timeout_waits_for_async_cleanup_and_releases_waiting_count():
    module = load_bridge()
    cleaned = threading.Event()

    async def work():
        try:
            await asyncio.sleep(60)
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    with pytest.raises(FutureTimeoutError):
        module.run_async_task(work, timeout=0.05, cancel_grace=1)
    assert cleaned.is_set()
    assert module.get_worker_async_metrics()["waiting_tasks"] == 0
    assert module.run_async_task(lambda: asyncio.sleep(0, result=42)) == 42


async def test_bridge_rejects_event_loop_caller_before_creating_coroutine():
    module = load_bridge()

    def forbidden():
        raise AssertionError("factory must not run")

    with pytest.raises(RuntimeError, match="event-loop thread"):
        module.run_async_task(forbidden)


def test_bridge_context_isolated_and_business_timeout_not_retried():
    module = load_bridge()
    tenant = contextvars.ContextVar("tenant", default=None)

    async def read():
        await asyncio.sleep(0.001)
        return tenant.get()

    def submit(i):
        tenant.set(i)
        return module.run_async_task(read, timeout=1)

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(submit, range(12))) == list(range(12))
    error = TimeoutError("business timeout")

    async def fail():
        raise error

    with pytest.raises(TimeoutError) as caught:
        module.run_async_task(fail, timeout=1)
    assert caught.value is error


def test_loop_lag_is_observable_and_warning_is_throttled(monkeypatch, caplog):
    module = load_bridge()
    monkeypatch.setattr(module.time, "monotonic", lambda: 100.0)
    module._last_loop_tick = 90.0
    module._waiting_tasks = 3
    assert module.get_worker_async_metrics() == {"waiting_tasks": 3, "loop_lag_seconds": 9.0}
    module._warn_if_loop_stalled()
    module._warn_if_loop_stalled()
    assert len(caplog.records) == 1
    assert "waiting=3" in caplog.text
