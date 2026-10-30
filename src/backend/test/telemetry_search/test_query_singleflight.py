"""Identical in-flight loads are shared, and one cancellation does not fail the other."""

import asyncio

import pytest

from bisheng.telemetry_search.domain.services.query_singleflight import shared_call


@pytest.fixture(autouse=True)
def _clear_flights():
    from bisheng.telemetry_search.domain.services import query_singleflight

    query_singleflight._tasks.clear()
    yield
    query_singleflight._tasks.clear()


async def test_cancelled_waiter_leaves_the_other_result():
    started = asyncio.Event()
    release = asyncio.Event()

    async def work():
        started.set()
        await release.wait()
        return 7

    first = asyncio.create_task(shared_call("same", work))
    await started.wait()
    second = asyncio.create_task(shared_call("same", work))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert await second == 7


async def test_finished_load_is_not_reused():
    calls = 0

    async def work():
        nonlocal calls
        calls += 1
        return calls

    assert await shared_call("once", work) == 1
    assert await shared_call("once", work) == 2
