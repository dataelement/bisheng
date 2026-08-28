"""Overload protection for OpenFGA: the gate and the middleware that fronts it."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.errcode.server import OpenFgaOverloadedError
from bisheng.common.middleware import openfga_guard as guard_module
from bisheng.common.middleware.openfga_guard import OpenFgaGuardMiddleware
from bisheng.core.config.openfga import OpenFgaGuardConf
from bisheng.core.openfga.concurrency import OpenFgaConcurrencyGate
from bisheng.core.openfga.exceptions import FGAOverloadError


@pytest.fixture
def gate() -> OpenFgaConcurrencyGate:
    instance = OpenFgaConcurrencyGate()
    instance.configure(enabled=True, max_in_flight=4, reject_ratio=0.75, acquire_timeout=0.05)
    return instance


async def test_gate_admits_up_to_capacity(gate):
    release = asyncio.Event()

    async def hold():
        async with gate.slot():
            await release.wait()

    tasks = [asyncio.create_task(hold()) for _ in range(4)]
    await asyncio.sleep(0.01)

    assert gate.in_flight == 4
    assert gate.occupancy == 1.0

    release.set()
    await asyncio.gather(*tasks)
    assert gate.in_flight == 0


async def test_gate_rejects_once_full(gate):
    release = asyncio.Event()

    async def hold():
        async with gate.slot():
            await release.wait()

    tasks = [asyncio.create_task(hold()) for _ in range(4)]
    await asyncio.sleep(0.01)

    with pytest.raises(FGAOverloadError):
        async with gate.slot():
            pass

    release.set()
    await asyncio.gather(*tasks)


async def test_overloaded_at_configured_threshold(gate):
    """Shedding starts at the threshold, not only when the gate is completely full."""
    release = asyncio.Event()

    async def hold():
        async with gate.slot():
            await release.wait()

    tasks = [asyncio.create_task(hold()) for _ in range(2)]
    await asyncio.sleep(0.01)
    assert gate.occupancy == 0.5
    assert gate.is_overloaded() is False

    tasks.append(asyncio.create_task(hold()))
    await asyncio.sleep(0.01)
    assert gate.occupancy == 0.75
    assert gate.is_overloaded() is True

    release.set()
    await asyncio.gather(*tasks)


async def test_disabled_gate_never_blocks(gate):
    gate.configure(enabled=False, max_in_flight=1, reject_ratio=0.1, acquire_timeout=0.01)

    async with gate.slot():
        async with gate.slot():
            assert gate.in_flight == 0

    assert gate.is_overloaded() is False


async def test_capacity_change_takes_effect(gate):
    gate.configure(enabled=True, max_in_flight=1, reject_ratio=1.0, acquire_timeout=0.05)
    release = asyncio.Event()

    async def hold():
        async with gate.slot():
            await release.wait()

    task = asyncio.create_task(hold())
    await asyncio.sleep(0.01)
    with pytest.raises(FGAOverloadError):
        async with gate.slot():
            pass

    # Raising the ceiling must let new callers in without waiting for a drain.
    gate.configure(enabled=True, max_in_flight=8, reject_ratio=1.0, acquire_timeout=0.05)
    async with gate.slot():
        pass

    release.set()
    await task


def test_reject_percent_drives_user_facing_text(gate):
    gate.configure(enabled=True, max_in_flight=10, reject_ratio=0.85, acquire_timeout=1)
    assert gate.reject_percent == 85


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(OpenFgaGuardMiddleware)

    @app.get('/api/v1/anything')
    def anything():
        return {'ok': True}

    @app.get('/health')
    def health():
        return {'status': 'OK'}

    return app


@pytest.fixture
def guard_env(monkeypatch):
    conf = OpenFgaGuardConf(enabled=True, max_in_flight=4, reject_ratio=0.5, acquire_timeout=0.05)

    async def fake_conf():
        return conf

    monkeypatch.setattr(guard_module, '_load_guard_conf', fake_conf)
    monkeypatch.setattr(guard_module, '_cached_conf', None)
    return conf


def test_middleware_passes_through_when_idle(guard_env):
    with TestClient(_build_app()) as client:
        assert client.get('/api/v1/anything').json() == {'ok': True}


def test_middleware_sheds_when_saturated(guard_env, monkeypatch):
    monkeypatch.setattr(guard_module.openfga_gate, 'is_overloaded', lambda: True)

    with TestClient(_build_app()) as client:
        response = client.get('/api/v1/anything')

    # HTTP 200 with a business code in the envelope: integrators branch on
    # status_code, and a non-2xx would read as a transport failure to them.
    assert response.status_code == 200
    body = response.json()
    assert body['status_code'] == OpenFgaOverloadedError.Code
    assert '%' in body['status_message']
    assert response.headers['Retry-After'] == '60'


def test_middleware_converts_late_overload_into_the_same_answer(guard_env):
    app = FastAPI()
    app.add_middleware(OpenFgaGuardMiddleware)

    @app.get('/api/v1/late')
    def late():
        raise FGAOverloadError('gate filled up mid-request')

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/api/v1/late')

    assert response.status_code == OpenFgaOverloadedError.HttpStatus
    assert response.json()['data']['reason'] == 'gate_wait_timeout'


def test_middleware_leaves_excluded_paths_alone(guard_env, monkeypatch):
    monkeypatch.setattr(guard_module.openfga_gate, 'is_overloaded', lambda: True)

    with TestClient(_build_app()) as client:
        assert client.get('/health').json() == {'status': 'OK'}
