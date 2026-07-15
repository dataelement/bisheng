from __future__ import annotations

import asyncio
import contextvars
import importlib.util
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from bisheng.core.database.connection import DatabaseConnectionManager
from bisheng.utils import async_utils

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _load_worker_asyncio_utils():
    module_path = BACKEND_ROOT / "bisheng" / "worker" / "_asyncio_utils.py"
    spec = importlib.util.spec_from_file_location("celery_asyncio_utils_runtime_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


worker_asyncio_utils = _load_worker_asyncio_utils()


def test_async_database_engine_is_scoped_to_event_loop(monkeypatch) -> None:
    created = []

    class _FakeAsyncEngine:
        def __init__(self, index: int):
            self.index = index
            self.dialect = SimpleNamespace(name="mysql")

        async def dispose(self):
            return None

    def _fake_create_async_engine(*_args, **_kwargs):
        engine = _FakeAsyncEngine(len(created))
        created.append(engine)
        return engine

    monkeypatch.setattr(
        "bisheng.core.database.connection.create_async_engine",
        _fake_create_async_engine,
    )

    manager = DatabaseConnectionManager("mysql+pymysql://user:pass@127.0.0.1/db")

    async def _get_engine():
        return manager.async_engine

    first_loop_engine = asyncio.run(_get_engine())
    second_loop_engine = asyncio.run(_get_engine())

    assert first_loop_engine is not second_loop_engine
    assert [engine.index for engine in created] == [0, 1]


def test_find_task_node_sync_uses_sync_alive_node_refresh(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.main",
        SimpleNamespace(WORKER_ALIVE_KEY="celery_worker_alive_queues"),
    )

    module_path = BACKEND_ROOT / "bisheng" / "worker" / "utils" / "stateful_worker.py"
    spec = importlib.util.spec_from_file_location(
        "stateful_worker_sync_runtime_test",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    worker = module.StatefulWorker()
    called = {"sync_refresh": False}

    def _forbidden_async_refresh():
        raise AssertionError("sync path must not call async refresh")

    def _sync_refresh():
        called["sync_refresh"] = True

    monkeypatch.setattr(worker, "update_alive_nodes", _forbidden_async_refresh)
    monkeypatch.setattr(worker, "update_alive_nodes_sync", _sync_refresh)
    monkeypatch.setattr(worker, "_find_bound_node_sync", lambda _hash_key: None)
    monkeypatch.setattr(worker, "_save_bound_node_sync", lambda _hash_key, _node: None)
    monkeypatch.setattr(worker.consistent_hash, "find_node", lambda _hash_key: "worker-a")

    assert worker.find_task_node_sync("chat-1") == "worker-a"
    assert called["sync_refresh"] is True


async def _running_loop_id() -> int:
    return id(asyncio.get_running_loop())


class _LoopBoundResource:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None

    async def use(self) -> int:
        current = asyncio.get_running_loop()
        if self.loop is None:
            self.loop = current
        elif self.loop is not current:
            raise RuntimeError("resource used from a different loop")
        return id(current)


def test_run_async_safe_uses_registered_worker_loop() -> None:
    worker_loop = worker_asyncio_utils.get_worker_loop()

    assert async_utils.run_async_safe(_running_loop_id(), timeout=1) == id(worker_loop)


def test_run_async_safe_and_run_async_task_share_loop_bound_resource() -> None:
    worker_asyncio_utils.get_worker_loop()
    resource = _LoopBoundResource()

    bridge_loop_id = async_utils.run_async_safe(resource.use(), timeout=1)
    task_loop_id = worker_asyncio_utils.run_async_task(resource.use)

    assert bridge_loop_id == task_loop_id


def test_registered_worker_loop_preserves_contextvars_across_threads() -> None:
    worker_asyncio_utils.get_worker_loop()
    tenant_probe = contextvars.ContextVar("tenant_probe", default="unset")

    async def _read_context() -> tuple[str, int]:
        return tenant_probe.get(), id(asyncio.get_running_loop())

    def _submit(index: int) -> tuple[str, int]:
        tenant_probe.set(f"tenant-{index}")
        return async_utils.run_async_safe(_read_context(), timeout=1)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_submit, range(16)))

    assert [value for value, _ in results] == [f"tenant-{index}" for index in range(16)]
    assert {loop_id for _, loop_id in results} == {id(worker_asyncio_utils.get_worker_loop())}


def test_registered_worker_loop_propagates_original_exception() -> None:
    worker_asyncio_utils.get_worker_loop()

    async def _raise() -> None:
        raise LookupError("bridge failure")

    with pytest.raises(LookupError, match="bridge failure"):
        async_utils.run_async_safe(_raise(), timeout=1)


def test_run_async_safe_keeps_plain_sync_fallback_without_worker_loop() -> None:
    async_utils.set_preferred_bridge_loop(None)
    resource = _LoopBoundResource()

    try:
        first_loop_id = async_utils.run_async_safe(resource.use(), timeout=1)
        second_loop_id = async_utils.run_async_safe(resource.use(), timeout=1)
    finally:
        async_utils.set_preferred_bridge_loop(worker_asyncio_utils.get_worker_loop())

    assert first_loop_id == second_loop_id
    assert first_loop_id != id(worker_asyncio_utils.get_worker_loop())


def test_worker_shutdown_unregisters_preferred_bridge_loop() -> None:
    script = r"""
from unittest.mock import patch

from bisheng.worker import main

with patch("bisheng.utils.async_utils.set_preferred_bridge_loop") as unregister:
    main.on_worker_shutdown()
    unregister.assert_called_once_with(None)
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
