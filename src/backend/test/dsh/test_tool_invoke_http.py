"""AC-08, AC-09, AC-13, AC-17: authenticated bounded HTTP admission."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import ClientDisconnect

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError
from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.api.endpoints import tools
from bisheng.dsh.domain.schemas.tool_publications import ToolLimits
from bisheng.dsh.tool_runtime import get_tool_service
from test.dsh.test_tool_publications import principal


@pytest.fixture
def http_setup():
    app = FastAPI()
    app.include_router(tools.router, prefix="/api/v1")
    runtime = SimpleNamespace(access=SimpleNamespace(authenticate=AsyncMock(return_value=principal())))
    service = SimpleNamespace(
        preflight=AsyncMock(return_value=ToolLimits()),
        invoke=AsyncMock(return_value={"tool": "bs_web_search", "result": {"results": [], "truncated": False}}),
    )
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_tool_service] = lambda: service
    return app, runtime, service


async def test_top_level_contract(http_setup):
    app, _, service = http_setup
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
        response = await client.post(
            "/api/v1/dsh/tools/bs_web_search/invoke",
            headers={"Authorization": "Bearer verified"},
            json={"arguments": {"query": "x"}},
        )
    assert response.status_code == 200
    assert set(response.json()) == {"tool", "result"}
    assert response.headers["cache-control"] == "no-store"
    assert service.invoke.await_args.args[:3] == (principal(), "bs_web_search", {"query": "x"})


@pytest.mark.parametrize(
    "body,query,status",
    [
        ('{"arguments":{},"arguments":{}}', "", 400),
        ('{"arguments":{},"url":"https://bad"}', "", 400),
        ('{"arguments":{}}', "?tenant_id=9", 400),
        ('{"arguments":{"x":NaN}}', "", 400),
        ("x" * 65537, "", 413),
    ],
)
async def test_strict_body(http_setup, body, query, status):
    app, _, service = http_setup
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
        response = await client.post(
            "/api/v1/dsh/tools/search/invoke" + query,
            headers={"Authorization": "Bearer verified", "Content-Type": "application/json"},
            content=body,
        )
    assert response.status_code == status
    assert set(response.json()) == {"error", "request_id"}
    service.invoke.assert_not_awaited()


async def test_auth_before_malformed_body(http_setup):
    app, runtime, service = http_setup
    runtime.access.authenticate.side_effect = DshInvalidAccessTokenError()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
        response = await client.post(
            "/api/v1/dsh/tools/search/invoke", headers={"Authorization": "Bearer PAT"}, content="invalid"
        )
        cookie = await client.post(
            "/api/v1/dsh/tools/search/invoke", headers={"Cookie": "access_token_cookie=browser"}, content="invalid"
        )
    assert response.status_code == cookie.status_code == 401
    runtime.access.authenticate.assert_awaited_once()
    service.invoke.assert_not_awaited()


async def test_disconnect_cancels_inflight_execution(http_setup):
    """AC-29: ASGI disconnect cancels the upstream task and awaits its cleanup."""
    app, _, service = http_setup
    started, cleaned = asyncio.Event(), asyncio.Event()

    async def block(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    service.invoke.side_effect = block
    events = [{"type": "http.request", "body": b'{"arguments":{"query":"x"}}', "more_body": False}]

    async def receive():
        if events:
            return events.pop()
        await started.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        assert message["type"] != "http.response.start" or message["status"] != 200

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/dsh/tools/search/invoke",
        "query_string": b"",
        "headers": [(b"authorization", b"Bearer verified"), (b"content-type", b"application/json")],
        "server": ("test", 80),
        "client": ("test", 1),
        "root_path": "",
    }
    with pytest.raises(ClientDisconnect):
        await asyncio.wait_for(app(scope, receive, send), timeout=2)
    assert cleaned.is_set()


async def test_unknown_failure_uses_safe_real_error_envelope(http_setup):
    """AC-20, AC-21: unexpected provider details do not escape in the response."""
    app, _, service = http_setup
    service.invoke.side_effect = RuntimeError("private provider payload")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
        response = await client.post(
            "/api/v1/dsh/tools/search/invoke",
            headers={"Authorization": "Bearer verified"},
            json={"arguments": {"query": "x"}},
        )
    assert response.status_code == 500 and response.json()["error"]["code"] == "internal_error"
    assert "private" not in response.text and response.headers["cache-control"] == "no-store"


async def test_published_body_cap_and_openapi(http_setup):
    """AC-27, AC-28: tighten the streaming cap before buffering the request."""
    app, _, service = http_setup
    service.preflight.return_value = ToolLimits(max_input_bytes=10)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
        response = await client.post(
            "/api/v1/dsh/tools/search/invoke",
            headers={"Authorization": "Bearer verified"},
            json={"arguments": {"query": "x"}},
        )
    assert response.status_code == 413
    service.invoke.assert_not_awaited()
    schema = app.openapi()["paths"]["/api/v1/dsh/tools/{toolCode}/invoke"]["post"]["requestBody"]
    assert schema["content"]["application/json"]["schema"]["required"] == ["arguments"]
