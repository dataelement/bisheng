import json
from contextlib import asynccontextmanager

import pytest

from bisheng.common.errcode.open_api import OpenApiCredentialMissingError
from bisheng.open_mcp.auth import OpenMcpTransportAuth, get_current_mcp_scope


def _scope(*, headers=None):
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/v2/mcp",
        "headers": headers or [],
        "client": ("192.0.2.67", 12345),
    }


async def _invoke(app, scope, request_messages):
    messages = list(request_messages)
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    return sent


def _response_json(messages):
    body = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    return json.loads(body)


@pytest.mark.asyncio
async def test_transport_auth_propagates_identity_headers_and_scope(monkeypatch):
    captured = {}

    @asynccontextmanager
    async def _access_context(**kwargs):
        captured.update(kwargs)
        yield

    async def inner(scope, receive, send):
        captured["current_scope"] = get_current_mcp_scope()
        message = await receive()
        captured["body"] = message["body"]

    monkeypatch.setattr("bisheng.open_mcp.auth.open_api_access_context", _access_context)
    app = OpenMcpTransportAuth(inner)
    headers = [
        (b"authorization", b"Bearer f067"),
        (b"x-on-behalf-of", b"42"),
        (b"x-end-user", b"end-user"),
    ]
    body = b"{}"

    await _invoke(
        app,
        _scope(headers=headers),
        [{"type": "http.request", "body": body, "more_body": False}],
    )

    assert captured["authorization"] == "Bearer f067"
    assert captured["on_behalf_of"] == "42"
    assert captured["end_user"] == "end-user"
    assert captured["connection_scope"]["path"] == "/api/v2/mcp"
    assert captured["current_scope"]["client"][0] == "192.0.2.67"
    assert captured["body"] == body
    assert get_current_mcp_scope() is None


@pytest.mark.asyncio
async def test_transport_auth_returns_existing_open_api_auth_envelope(monkeypatch):
    @asynccontextmanager
    async def _reject(**kwargs):
        raise OpenApiCredentialMissingError()
        yield  # pragma: no cover

    monkeypatch.setattr("bisheng.open_mcp.auth.open_api_access_context", _reject)
    sent = await _invoke(
        OpenMcpTransportAuth(lambda scope, receive, send: None),
        _scope(),
        [{"type": "http.request", "body": b"", "more_body": False}],
    )

    start = next(item for item in sent if item["type"] == "http.response.start")
    assert start["status"] == 401
    assert _response_json(sent)["status_code"] == 26001


@pytest.mark.asyncio
async def test_transport_rejects_declared_body_over_limit_before_inner_app(monkeypatch):
    called = False

    @asynccontextmanager
    async def _access_context(**kwargs):
        yield

    async def inner(scope, receive, send):
        nonlocal called
        called = True

    monkeypatch.setattr("bisheng.open_mcp.auth.open_api_access_context", _access_context)
    from bisheng.open_mcp.auth import settings

    monkeypatch.setattr(
        type(settings.open_mcp),
        "max_request_body_bytes",
        property(lambda self: 4),
    )
    sent = await _invoke(
        OpenMcpTransportAuth(inner),
        _scope(headers=[(b"content-length", b"5")]),
        [{"type": "http.request", "body": b"12345", "more_body": False}],
    )

    assert called is False
    assert next(item for item in sent if item["type"] == "http.response.start")["status"] == 413
    assert _response_json(sent)["error"]["code"] == "REQUEST_TOO_LARGE"


@pytest.mark.asyncio
async def test_transport_rejects_streamed_body_over_limit(monkeypatch):
    @asynccontextmanager
    async def _access_context(**kwargs):
        yield

    async def inner(scope, receive, send):
        await receive()
        await receive()

    monkeypatch.setattr("bisheng.open_mcp.auth.open_api_access_context", _access_context)
    from bisheng.open_mcp.auth import settings

    monkeypatch.setattr(
        type(settings.open_mcp),
        "max_request_body_bytes",
        property(lambda self: 4),
    )
    sent = await _invoke(
        OpenMcpTransportAuth(inner),
        _scope(),
        [
            {"type": "http.request", "body": b"12", "more_body": True},
            {"type": "http.request", "body": b"345", "more_body": False},
        ],
    )

    assert next(item for item in sent if item["type"] == "http.response.start")["status"] == 413
