from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from bisheng.core.database.connection import DatabaseConnectionManager

BACKEND_ROOT = Path(__file__).resolve().parents[2]


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
