import asyncio
import time

import pytest

from bisheng.permission.domain.services.owner_service import _run_async_safe
from bisheng.utils.async_utils import run_async_safe


async def _sleep_then_return(delay: float, value: str = 'ok') -> str:
    await asyncio.sleep(delay)
    return value


def test_run_async_safe_runs_from_plain_sync_context():
    assert run_async_safe(_sleep_then_return(0), timeout=1) == 'ok'


def test_run_async_safe_honors_timeout_from_plain_sync_context():
    with pytest.raises(asyncio.TimeoutError):
        run_async_safe(_sleep_then_return(0.2), timeout=0.01)


@pytest.mark.asyncio
async def test_run_async_safe_rejects_running_event_loop_without_waiting():
    start = time.perf_counter()

    with pytest.raises(RuntimeError, match='running event loop'):
        run_async_safe(_sleep_then_return(1), timeout=5)

    assert time.perf_counter() - start < 0.5


@pytest.mark.asyncio
async def test_owner_run_async_safe_reuses_event_loop_guard():
    start = time.perf_counter()

    with pytest.raises(RuntimeError, match='running event loop'):
        _run_async_safe(_sleep_then_return(1), timeout=5)

    assert time.perf_counter() - start < 0.5
