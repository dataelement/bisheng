"""共享权限读取不能被单个请求取消污染。"""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from bisheng.core.openfga.client import FGAClient
from bisheng.core.openfga.exceptions import FGAClientError

OBJECT = "knowledge_space:3540"


@pytest.fixture
async def client():
    instance = FGAClient("http://openfga.test", "store", "model")
    yield instance
    await instance.close()


@pytest.mark.parametrize("cancel_index", [0, 1], ids=["owner", "joiner"])
async def test_cancelled_waiter_does_not_cancel_other_requests(client, monkeypatch, cancel_index):
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def read(path, body):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"tuples": [{"key": {"object": OBJECT, "relation": "viewer", "user": "user:1"}}]}

    monkeypatch.setattr(client, "_post", read)
    tasks = [asyncio.create_task(client.read_tuples(object=OBJECT)) for _ in range(2)]
    try:
        await asyncio.wait_for(started.wait(), 1)
        tasks[cancel_index].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[cancel_index]
        release.set()
        result = await asyncio.wait_for(tasks[1 - cancel_index], 1)
        assert result == [{"object": OBJECT, "relation": "viewer", "user": "user:1"}]
        assert await client.read_tuples(object=OBJECT) == result
        assert calls == 1
    finally:
        release.set()
        for task in tasks:
            task.cancel()
        # 断言失败时也回收测试创建的请求。
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("fails", [False, True], ids=["success", "failure"])
async def test_abandoned_read_finishes_and_cleans_up(client, monkeypatch, caplog, fails):
    started, release = asyncio.Event(), asyncio.Event()

    async def read(path, body):
        started.set()
        await release.wait()
        if fails:
            raise FGAClientError("abandoned read failed")
        return {"tuples": []}

    monkeypatch.setattr(client, "_post", read)
    waiter = asyncio.create_task(client.read_tuples(object=OBJECT))
    await asyncio.wait_for(started.wait(), 1)
    shared = next(iter(client._read_tuple_inflight.values()))[0]
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release.set()
    # 不再等待共享任务的结果。验证客户端自己完成回收和异常记录。
    finished = asyncio.Event()
    shared.add_done_callback(lambda _: finished.set())
    await asyncio.wait_for(finished.wait(), 1)
    assert not shared.cancelled()
    assert client._read_tuple_inflight == {}
    if fails:
        assert "abandoned read failed" in caplog.text
    monkeypatch.setattr(client, "_post", AsyncMock(return_value={"tuples": []}))
    assert await client.read_tuples(object=OBJECT) == []
    assert client._post.await_count == int(fails)


async def test_stale_cancelled_read_does_not_break_http_response(client, monkeypatch):
    stale = asyncio.create_task(asyncio.sleep(0))
    stale.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stale
    key = client._read_tuple_cache_key(None, None, OBJECT)
    client._read_tuple_inflight[key] = (stale, client._read_tuple_cache_generation)
    monkeypatch.setattr(client, "_post", AsyncMock(return_value={"tuples": []}))

    async def children(request):
        return JSONResponse(await client.read_tuples(object=OBJECT))

    async def dispatch(request, call_next):
        return await call_next(request)

    app = Starlette(routes=[Route("/children", children)])
    app.add_middleware(BaseHTTPMiddleware, dispatch=dispatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as http:
        response = await http.get("/children")
        assert response.status_code == 200
        assert response.json() == []


async def test_cancelled_shared_operation_is_not_reused(client, monkeypatch):
    monkeypatch.setattr(client, "_post", AsyncMock(side_effect=[asyncio.CancelledError(), {"tuples": []}]))
    with pytest.raises(asyncio.CancelledError):
        await client.read_tuples(object=OBJECT)
    assert await client.read_tuples(object=OBJECT) == []


async def test_close_collects_reads_displaced_by_cache_invalidation(client, monkeypatch):
    started = asyncio.Queue()

    async def read(path, body):
        started.put_nowait(True)
        await asyncio.Event().wait()

    monkeypatch.setattr(client, "_post", read)
    tasks = []
    try:
        for _ in range(2):
            tasks.append(asyncio.create_task(client.read_tuples(object=OBJECT)))
            await asyncio.wait_for(started.get(), 1)
            client.clear_read_tuples_cache()
        await client.close()
        for task in tasks:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
        assert client._read_tuple_inflight == {}
        with pytest.raises(RuntimeError, match="closed"):
            await client.read_tuples(object=OBJECT)
    finally:
        for task in tasks:
            task.cancel()
        # 回收故意挂起的测试请求。防止失败影响其他用例。
        await asyncio.gather(*tasks, return_exceptions=True)
