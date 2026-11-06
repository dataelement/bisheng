"""Concurrent startup must reuse one Store/model and stop waiting on timeout."""

from __future__ import annotations

import asyncio
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from bisheng.common.errcode.permission import AuthorizationModelMismatchError
from bisheng.core.config.openfga import OpenFGAConf
from bisheng.core.openfga.authorization_model_f048 import build_authorization_model_f048
from bisheng.core.openfga.discovery import OpenFGARuntimePin, discover_openfga_runtime
from bisheng.core.openfga.manager import FGAManager


@pytest.fixture
def redis_locks(monkeypatch):
    locks: dict[str, asyncio.Lock] = {}
    options = []

    def make_lock(key, **kwargs):
        options.append((key, kwargs))
        mutex = locks.setdefault(key, asyncio.Lock())
        return SimpleNamespace(acquire=mutex.acquire, release=AsyncMock(side_effect=mutex.release))

    getter = AsyncMock(return_value=SimpleNamespace(async_connection=SimpleNamespace(lock=make_lock)))
    monkeypatch.setattr("bisheng.core.openfga.manager.get_redis_client", getter)
    return SimpleNamespace(locks=locks, options=options, getter=getter)


class _OpenFGA:
    def __init__(self, starters: int, *, existing_store: bool = False):
        self.stores = [{"id": "store-one", "name": "bisheng"}] if existing_store else []
        self.models = []
        self.model = build_authorization_model_f048()
        self.writes = Counter()
        self.starters = starters
        self.reads = 0
        self.gate = asyncio.Event()
        self.gate_path = "/stores/store-one/authorization-models" if existing_store else "/stores"

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            self.writes[path] += 1
            await asyncio.sleep(0)
            if path == "/stores":
                row = {"id": "store-one", "name": "bisheng"}
                self.stores.append(row)
                return httpx.Response(201, json=row)
            row = {"id": "model-one"}
            self.models.append(row)
            return httpx.Response(201, json={"authorization_model_id": row["id"]})
        if path == "/stores":
            payload = {"stores": list(self.stores)}
        elif path.endswith("/authorization-models"):
            payload = {"authorization_models": list(self.models)}
        else:
            return httpx.Response(200, json={"authorization_model": self.model})
        # Capture empty responses before releasing all starting processes.
        if path == self.gate_path and self.reads < self.starters:
            self.reads += 1
            if self.reads == self.starters:
                self.gate.set()
            await self.gate.wait()
        return httpx.Response(200, json=payload)


def _manager():
    return FGAManager(OpenFGAConf(), environment="dev")


@pytest.mark.parametrize("existing_store", [False, True])
async def test_concurrent_starters_reuse_one_store_and_model(monkeypatch, redis_locks, existing_store):
    server = _OpenFGA(5, existing_store=existing_store)
    async with httpx.AsyncClient(
        base_url="http://openfga:8080", transport=httpx.MockTransport(server.handle)
    ) as client:

        async def discover(*args, **kwargs):
            return await discover_openfga_runtime(*args, **kwargs, http_client=client)

        monkeypatch.setattr("bisheng.core.openfga.manager.discover_openfga_runtime", discover)
        managers = [_manager() for _ in range(5)]
        await asyncio.wait_for(asyncio.gather(*(m._async_initialize() for m in managers)), timeout=3)

    assert len(server.stores) == len(server.models) == 1
    assert server.writes["/stores"] == (0 if existing_store else 1)
    assert server.writes["/stores/store-one/authorization-models"] == 1
    assert {(m.readiness()["store_id"], m.readiness()["model_id"]) for m in managers} == {("store-one", "model-one")}
    assert {key for key, _ in redis_locks.options} == {"openfga:bootstrap:bisheng"}
    assert all(o["timeout"] == 60 and o["blocking_timeout"] == 30 for _, o in redis_locks.options)


async def test_existing_runtime_does_not_acquire_bootstrap_lock(monkeypatch, redis_locks):
    server = _OpenFGA(0, existing_store=True)
    server.models = [{"id": "model-one"}]
    async with httpx.AsyncClient(
        base_url="http://openfga:8080", transport=httpx.MockTransport(server.handle)
    ) as client:

        async def discover(*args, **kwargs):
            return await discover_openfga_runtime(*args, **kwargs, http_client=client)

        monkeypatch.setattr("bisheng.core.openfga.manager.discover_openfga_runtime", discover)
        await _manager()._async_initialize()
    redis_locks.getter.assert_not_awaited()
    assert not server.writes


async def test_waiting_for_another_starter_has_a_deadline(monkeypatch, redis_locks):
    lock = asyncio.Lock()
    await lock.acquire()
    redis_locks.locks["openfga:bootstrap:bisheng"] = lock
    discover = AsyncMock(side_effect=AuthorizationModelMismatchError(msg="Store does not exist"))
    monkeypatch.setattr("bisheng.core.openfga.manager.discover_openfga_runtime", discover)
    manager = _manager()
    manager.timeout = 0.02
    try:
        with pytest.raises(TimeoutError, match="bootstrap timed out"):
            await asyncio.wait_for(manager._async_initialize(), timeout=0.5)
        assert lock.locked()  # A waiter must not release the owner's lock.
        assert all(not call.kwargs["allow_bootstrap"] for call in discover.await_args_list)
    finally:
        lock.release()


async def test_timed_out_writer_releases_lock(monkeypatch, redis_locks):
    async def slow_discover(*args, **kwargs):
        await asyncio.Event().wait()

    discover = AsyncMock(side_effect=slow_discover)
    monkeypatch.setattr("bisheng.core.openfga.manager.discover_openfga_runtime", discover)
    manager = _manager()
    manager.timeout = 0.02
    with pytest.raises(TimeoutError, match="bootstrap timed out"):
        await asyncio.wait_for(manager._bootstrap_runtime(build_authorization_model_f048()), timeout=0.5)
    assert not redis_locks.locks["openfga:bootstrap:bisheng"].locked()


async def test_redis_failure_never_falls_back_to_unlocked_writes(monkeypatch, redis_locks):
    redis_locks.getter.side_effect = RedisConnectionError("Redis unavailable")
    discover = AsyncMock()
    monkeypatch.setattr("bisheng.core.openfga.manager.discover_openfga_runtime", discover)
    with pytest.raises(RedisConnectionError):
        await _manager()._bootstrap_runtime(build_authorization_model_f048())
    discover.assert_not_awaited()


async def test_failed_writer_releases_lock_for_next_starter(monkeypatch, redis_locks):
    discover = AsyncMock(side_effect=AuthorizationModelMismatchError(msg="OpenFGA unavailable"))
    monkeypatch.setattr("bisheng.core.openfga.manager.discover_openfga_runtime", discover)
    with pytest.raises(AuthorizationModelMismatchError):
        await _manager()._bootstrap_runtime(build_authorization_model_f048())
    assert not redis_locks.locks["openfga:bootstrap:bisheng"].locked()
    pin = OpenFGARuntimePin("store-one", "model-one", "checksum")
    discover.side_effect = None
    discover.return_value = pin
    assert await _manager()._bootstrap_runtime(build_authorization_model_f048()) == pin


async def test_lock_acquisition_deadline_is_reported_as_bootstrap_timeout(monkeypatch, redis_locks):
    lock = SimpleNamespace(acquire=AsyncMock(return_value=False), release=AsyncMock())
    redis_locks.getter.return_value.async_connection.lock = lambda *args, **kwargs: lock
    discover = AsyncMock()
    monkeypatch.setattr("bisheng.core.openfga.manager.discover_openfga_runtime", discover)
    with pytest.raises(TimeoutError, match="bootstrap timed out after 30s"):
        await _manager()._bootstrap_runtime(build_authorization_model_f048())
    lock.release.assert_not_awaited()
    discover.assert_not_awaited()
