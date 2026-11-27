"""Self-contained regressions for D's terminal precheck and Redis cleanup."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.linsight.domain.services.task_message_broadcast import task_message_subscription


class Subscription:
    def __init__(self):
        self.closing = asyncio.Event()
        self.allow_close = asyncio.Event()
        self.closed = False

    async def subscribe(self, channel):
        self.channel = channel

    async def get_message(self, **kwargs):
        return {"type": "subscribe"}

    async def aclose(self):
        self.closing.set()
        await self.allow_close.wait()
        self.closed = True


async def test_repeated_cancellation_waits_for_pubsub_connection_release():
    subscription = Subscription()
    entered = asyncio.Event()

    async def viewer():
        async with task_message_subscription(SimpleNamespace(pubsub=lambda: subscription), "synthetic-task"):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(viewer())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    await asyncio.wait_for(subscription.closing.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done() and not subscription.closed
    subscription.allow_close.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert subscription.closed


async def test_failed_subscription_ack_also_releases_connection():
    subscription = Subscription()
    subscription.allow_close.set()
    subscription.get_message = AsyncMock(side_effect=ConnectionError("synthetic"))
    with pytest.raises(ConnectionError):
        async with task_message_subscription(SimpleNamespace(pubsub=lambda: subscription), "synthetic-task"):
            pytest.fail("must not enter before acknowledgement")
    assert subscription.closed


async def test_terminal_snapshot_never_requests_redis_subscription():
    path = Path(__file__).parents[2] / "bisheng/linsight/domain/services/message_stream_handle.py"
    tree = ast.parse(path.read_text())
    method = next(
        n
        for n in next(n for n in tree.body if isinstance(n, ast.ClassDef)).body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_send_stream"
    )
    scope = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(path), "exec"), scope)
    terminal = SimpleNamespace(model_dump=lambda: {"event_type": "final_result", "data": {"answer": "synthetic"}})
    subject = SimpleNamespace(
        _terminal_message=AsyncMock(return_value=terminal),
        send_json=AsyncMock(),
        _state_message_manager=SimpleNamespace(message_stream=lambda: pytest.fail("Redis requested")),
        _websocket=SimpleNamespace(close=AsyncMock()),
    )
    await scope["_send_stream"](subject)
    subject.send_json.assert_awaited_once_with(terminal.model_dump())
    subject._websocket.close.assert_awaited_once_with(code=1000, reason="Session finished")
