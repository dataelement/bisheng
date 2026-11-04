"""Real Redis acceptance for concurrent desktop/browser task subscriptions."""

import asyncio
import os
import pickle
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from bisheng.linsight.domain.services.task_message_broadcast import task_message_subscription


@pytest.fixture
async def redis_queue():
    url = os.getenv("TEST_TASK_REDIS_URL")
    if not url:
        pytest.skip("TEST_TASK_REDIS_URL enables real Redis stream acceptance")
    redis = Redis.from_url(url)
    key = f"task-broadcast-test:{uuid4().hex}:messages"
    try:
        yield redis, key
    finally:
        await redis.delete(key)
        await redis.aclose()


async def receive(iterator, count):
    frames = []
    async with asyncio.timeout(10):
        while len(frames) < count:
            frame = await anext(iterator)
            if frame is not None:
                frames.append(frame)
    return frames


async def test_two_clients_receive_the_same_ordered_stream_and_final_event(redis_queue):
    redis, key = redis_queue
    # Separate connections model sockets served by distinct API processes.
    other = Redis.from_url(os.environ["TEST_TASK_REDIS_URL"])
    try:
        async with task_message_subscription(redis, key) as desktop:
            async with task_message_subscription(other, key) as browser:
                expected = [{"event_type": "task_execute_step", "data": {"sequence": i}} for i in range(12)]
                expected.append({"event_type": "final_result", "data": {"output_result": {"answer": "done"}}})
                await redis.rpush(key, *(pickle.dumps(frame) for frame in expected))
                left, right = await asyncio.gather(receive(desktop, len(expected)), receive(browser, len(expected)))
                assert left == right == expected
                assert await redis.llen(key) == 0
    finally:
        await other.aclose()


async def test_pre_connection_backlog_and_legacy_worker_writes_are_delivered(redis_queue):
    redis, key = redis_queue
    expected = {"event_type": "task_generate", "data": {"tasks": [{"id": "task-1"}]}}
    await redis.rpush(key, pickle.dumps(expected))
    async with task_message_subscription(redis, key) as desktop:
        assert await receive(desktop, 1) == [expected]


async def test_disconnect_releases_only_its_subscription(redis_queue):
    redis, key = redis_queue
    async with task_message_subscription(redis, key) as desktop:
        async with task_message_subscription(redis, key):
            assert (await redis.pubsub_numsub(f"{key}:broadcast"))[0][1] == 2
        assert (await redis.pubsub_numsub(f"{key}:broadcast"))[0][1] == 1
        final = {"event_type": "final_result", "data": {"output_result": {}}}
        await redis.rpush(key, pickle.dumps(final))
        assert await receive(desktop, 1) == [final]
    assert (await redis.pubsub_numsub(f"{key}:broadcast"))[0][1] == 0


async def test_distinct_tasks_keep_their_events_separate(redis_queue):
    redis, key = redis_queue
    other_key = f"{key}:other"
    try:
        async with task_message_subscription(redis, key) as left:
            async with task_message_subscription(redis, other_key) as right:
                await redis.rpush(key, pickle.dumps({"id": "left"}))
                await redis.rpush(other_key, pickle.dumps({"id": "right"}))
                assert await asyncio.gather(receive(left, 1), receive(right, 1)) == [
                    [{"id": "left"}],
                    [{"id": "right"}],
                ]
    finally:
        await redis.delete(other_key)


async def test_real_websockets_both_finish_the_same_task(redis_queue, monkeypatch):
    import socket
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import uvicorn
    import websockets
    from fastapi import FastAPI, WebSocket

    from bisheng.linsight.domain.services import message_stream_handle as stream

    redis, key = redis_queue
    monkeypatch.setattr(
        stream,
        "LinsightStateMessageManager",
        lambda **_: SimpleNamespace(
            message_stream=lambda: task_message_subscription(redis, key),
        ),
    )
    monkeypatch.setattr(stream.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=None))
    app = FastAPI()

    @app.websocket("/stream")
    async def task_stream(websocket: WebSocket):
        await stream.MessageStreamHandle(websocket, "fixture-version").connect()

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    url = f"ws://127.0.0.1:{listener.getsockname()[1]}/stream"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(0.01)
        async with websockets.connect(url) as desktop:
            async with websockets.connect(url) as browser:
                async with asyncio.timeout(5):
                    while (await redis.pubsub_numsub(f"{key}:broadcast"))[0][1] < 2:
                        await asyncio.sleep(0.01)
                events = [
                    {"event_type": "task_generate", "data": {"tasks": [{"id": "one"}]}},
                    {"event_type": "task_end", "data": {"id": "one", "status": "success"}},
                    {"event_type": "final_result", "data": {"output_result": {"answer": "done", "final_files": []}}},
                ]
                await redis.rpush(key, *(pickle.dumps(frame) for frame in events))

                async def read(socket):
                    import json

                    async with asyncio.timeout(5):
                        return [json.loads(await socket.recv()) for _ in events]

                for frames in await asyncio.gather(read(desktop), read(browser)):
                    assert [{"event_type": frame["event_type"], "data": frame["data"]} for frame in frames] == events
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, timeout=5)
        listener.close()
