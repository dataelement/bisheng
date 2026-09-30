"""取消信号及 ASGI 消息诊断必须保持原有请求行为。"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.testclient import TestClient

from bisheng.common.middleware.http_request_diagnostics import HttpRequestDiagnosticsMiddleware


@pytest.fixture
def records():
    captured = []
    sink = logger.add(lambda message: captured.append(message.record))
    try:
        yield captured
    finally:
        logger.remove(sink)


def scope():
    return {"type": "http", "method": "GET", "path": "/probe", "headers": [], "query_string": b""}


@pytest.mark.parametrize("disconnected", [False, True])
async def test_cancellation_propagates_once_and_cleanup_runs(records, disconnected):
    cancelled = asyncio.CancelledError("request cancelled")
    events = []

    async def downstream(scope, receive, send):
        events.append("entered")
        try:
            if disconnected:
                assert (await receive())["type"] == "http.disconnect"
            raise cancelled
        finally:
            events.append("cleanup")

    receive = AsyncMock(return_value={"type": "http.disconnect"})
    send = AsyncMock()
    with pytest.raises(asyncio.CancelledError) as caught:
        await HttpRequestDiagnosticsMiddleware(downstream)(scope(), receive, send)
    assert caught.value is cancelled
    assert events == ["entered", "cleanup"]
    assert receive.await_count == int(disconnected)
    send.assert_not_awaited()
    message = next(row["message"] for row in records if "event=http_request_cancelled" in row["message"])
    assert f"disconnect_received={disconnected}" in message
    assert "response_started=False" in message
    assert not any("event=http_no_response" in row["message"] for row in records)


async def test_stream_messages_are_unchanged_and_not_prefetched(records):
    messages = [
        {"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]},
        {"type": "http.response.body", "body": b"data: ok\n\n", "more_body": True},
        {"type": "http.response.body", "body": b"", "more_body": False},
    ]
    request_message = {"type": "http.request", "body": b"body", "more_body": False}

    async def downstream(scope, receive, send):
        assert await receive() is request_message
        for message in messages:
            await send(message)

    receive, send = AsyncMock(return_value=request_message), AsyncMock()
    await HttpRequestDiagnosticsMiddleware(downstream)(scope(), receive, send)
    receive.assert_awaited_once()
    assert [call.args[0] for call in send.await_args_list] == messages
    assert not records


async def test_empty_downstream_is_diagnosed_without_fabricating_response(records):
    downstream, receive, send = AsyncMock(), AsyncMock(), AsyncMock()
    await HttpRequestDiagnosticsMiddleware(downstream)(scope(), receive, send)
    downstream.assert_awaited_once()
    receive.assert_not_awaited()
    send.assert_not_awaited()
    assert any("event=http_no_response" in row["message"] for row in records)


def test_cancellation_is_logged_before_base_middleware_wraps_it(records):
    # 使用真实 BaseHTTPMiddleware 的透传 dispatch，复现原来的错误包装。
    async def dispatch(request, call_next):
        return await call_next(request)

    app = FastAPI()
    app.add_middleware(HttpRequestDiagnosticsMiddleware)
    app.add_middleware(BaseHTTPMiddleware, dispatch=dispatch)
    calls = []

    @app.get("/cancel")
    async def cancel():
        calls.append("entered")
        raise asyncio.CancelledError()

    with TestClient(app) as client:
        with pytest.raises(RuntimeError, match="No response returned"):
            client.get("/cancel")
    assert calls == ["entered"]
    assert any("event=http_request_cancelled" in row["message"] for row in records)
