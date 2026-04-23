import asyncio
import sys

import pytest

from bisheng.permission.domain.services import owner_service as owner_mod


async def _sample():
    return 'ok'


def test_run_async_safe_uses_anyio_bridge_when_available(monkeypatch):
    monkeypatch.setattr(asyncio, 'get_running_loop', lambda: (_ for _ in ()).throw(RuntimeError()))

    class _FromThread:
        @staticmethod
        def run(fn, awaitable):
            awaitable.close()
            return 'bridged'

    monkeypatch.setitem(sys.modules, 'anyio', type('AnyIO', (), {'from_thread': _FromThread})())

    assert owner_mod._run_async_safe(_sample()) == 'bridged'


def test_run_async_safe_falls_back_only_without_worker_bridge(monkeypatch):
    monkeypatch.setattr(asyncio, 'get_running_loop', lambda: (_ for _ in ()).throw(RuntimeError()))

    class _FromThread:
        @staticmethod
        def run(fn, awaitable):
            raise RuntimeError('This function can only be run from an AnyIO worker thread')

    monkeypatch.setitem(sys.modules, 'anyio', type('AnyIO', (), {'from_thread': _FromThread})())
    monkeypatch.setattr(asyncio, 'run', lambda coro: (coro.close(), 'standalone')[1])

    assert owner_mod._run_async_safe(_sample()) == 'standalone'


def test_run_async_safe_does_not_mask_bridge_errors_with_new_loop(monkeypatch):
    monkeypatch.setattr(asyncio, 'get_running_loop', lambda: (_ for _ in ()).throw(RuntimeError()))

    class _FromThread:
        @staticmethod
        def run(fn, awaitable):
            raise ValueError('bridge failed')

    monkeypatch.setitem(sys.modules, 'anyio', type('AnyIO', (), {'from_thread': _FromThread})())

    called = False

    def _run(_):
        nonlocal called
        called = True
        return 'unexpected'

    monkeypatch.setattr(asyncio, 'run', _run)

    with pytest.raises(ValueError, match='bridge failed'):
        owner_mod._run_async_safe(_sample())

    assert called is False
