"""覆盖 AC: AC-04, AC-05, AC-07, AC-09 — actual API handlers and SDK transports."""

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from bisheng.core.config.dsh import DshSettings
from bisheng.dsh.access_runtime import get_runtime
from bisheng.dsh.api.endpoints import identity, local_auth, self_service
from bisheng.dsh.domain.services.authorization import DshAuthorizationService
from bisheng.dsh.request_origin import require_client_browser_origin, resolve_client_origin
from bisheng.dsh.work_mcp import (
    RequestScopedWorkMcpRuntime,
    WorkMcpResponse,
    create_work_mcp_runtime,
)


@pytest.mark.parametrize("origin", ["http://192.0.2.10:3001", "https://work.example:8443", "http://[::1]:8090"])
async def test_address_optional_authorization_and_browser_approval(origin):
    redis = SimpleNamespace(eval=AsyncMock(return_value=1), set=AsyncMock(return_value=True))
    runtime = SimpleNamespace(
        settings=DshSettings(),
        authorizations=DshAuthorizationService(redis, None),
        identity=SimpleNamespace(authorize=AsyncMock(return_value={"identity_ticket": "test-ticket"})),
    )
    app = FastAPI()
    app.include_router(local_auth.router)
    app.include_router(identity.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[identity.browser_user] = lambda: SimpleNamespace(user_id=42, tenant_id=2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=origin) as client:
        response = await client.post(
            "/dsh/authorizations",
            json={
                "client_id": "dsh-desktop",
                "redirect_uri": "http://127.0.0.1:49152/dsh/callback",
                "code_challenge": base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("="),
                "code_challenge_method": "S256",
                "state": "s" * 32,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["authorize_url"].startswith(origin + "/desktop-login?auth_id=")
        approved = await client.post(
            "/dsh/authorize", json={"auth_id": response.json()["auth_id"]}, headers={"origin": origin}
        )
        assert approved.json()["data"]["identity_ticket"] == "test-ticket"
        denied = await client.post(
            "/dsh/authorize", json={"auth_id": "wrong-origin"}, headers={"origin": "https://evil.example"}
        )
        assert denied.status_code == 403
        assert runtime.settings.platform_public_url is None


async def test_address_optional_session_revocation():
    service = SimpleNamespace(
        runtime=SimpleNamespace(settings=DshSettings()), revoke=AsyncMock(return_value={"revoked": True})
    )
    app = FastAPI()
    app.include_router(self_service.router)
    app.dependency_overrides[self_service.self_service] = lambda: service
    from bisheng.common.dependencies.user_deps import UserPayload

    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=42, tenant_id=2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://work.example:3001") as client:
        path = "/dsh/me/sessions/00000000-0000-0000-0000-000000000001/revoke"
        assert (await client.post(path, json={}, headers={"origin": "http://work.example:3001"})).json()["data"][
            "revoked"
        ]
        assert (await client.post(path, json={}, headers={"origin": "http://evil.example:3001"})).status_code == 403
        assert (await client.post(path, json={})).status_code == 403
        service.revoke.assert_awaited_once()


async def test_forwarded_scheme_requires_trusted_peer_and_host_is_never_forwarded():
    async def endpoint(request):
        settings = DshSettings(trusted_proxy_hosts=["192.0.2.1"])
        await require_client_browser_origin(request, settings)
        return JSONResponse({"origin": await resolve_client_origin(request, settings)})

    app = Starlette(routes=[Route("/origin", endpoint)])
    headers = {"x-forwarded-proto": "https", "x-forwarded-host": "evil.example", "origin": "https://work.example:8443"}
    for peer, expected in [("192.0.2.1", 200), ("192.0.2.2", 403)]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=(peer, 123)), base_url="http://work.example:8443"
        ) as client:
            response = await client.get("/origin", headers=headers)
            assert response.status_code == expected
            if expected == 200:
                assert response.json()["origin"] == "https://work.example:8443"


async def test_service_dns_trust_matches_the_current_proxy_peer(monkeypatch):
    async def endpoint(request):
        return JSONResponse(
            {"origin": await resolve_client_origin(request, DshSettings(trusted_proxy_hosts=["frontend-peers"]))}
        )

    lookup = AsyncMock(return_value=[(2, 1, 6, "", ("192.0.2.1", 0))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    app = Starlette(routes=[Route("/origin", endpoint)])
    for peer, scheme in [("192.0.2.1", "https"), ("192.0.2.2", "http")]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=(peer, 123)), base_url="http://work.example:3001"
        ) as client:
            response = await client.get("/origin", headers={"x-forwarded-proto": "https"})
            assert response.json()["origin"] == scheme + "://work.example:3001"


@pytest.mark.parametrize(
    "headers",
    [[], [("host", "one.example"), ("host", "two.example")], [("host", "example/path")], [("host", "user@example")]],
)
async def test_dynamic_address_rejects_ambiguous_authority(headers):
    from fastapi import HTTPException
    from starlette.requests import HTTPConnection

    connection = HTTPConnection(
        {"type": "http", "scheme": "http", "headers": [(name.encode(), value.encode()) for name, value in headers]}
    )
    with pytest.raises(HTTPException) as error:
        await resolve_client_origin(connection, DshSettings())
    assert error.value.status_code == 421


async def test_dynamic_sdk_policies_are_concurrent_and_request_scoped(monkeypatch):
    service = SimpleNamespace(
        list_tools=AsyncMock(return_value=[{"name": "echo", "description": "test", "inputSchema": {"type": "object"}}]),
        call_tool=AsyncMock(return_value={"ok": True}),
        list_skills=AsyncMock(
            return_value=[
                {"uri": "bisheng-skill://2/9/" + "a" * 64, "name": "test", "title": "Test", "description": "test"}
            ]
        ),
        read_skill=AsyncMock(return_value={"files": []}),
    )
    monkeypatch.setattr("bisheng.dsh.work_mcp.WorkCapabilitiesService", lambda user: service)
    from bisheng.common.services import config_service

    monkeypatch.setattr(config_service, "settings", SimpleNamespace(dsh=DshSettings()))
    manager = create_work_mcp_runtime()
    assert isinstance(manager, RequestScopedWorkMcpRuntime)

    async def endpoint(request):
        return WorkMcpResponse(manager, SimpleNamespace(user_id=42, tenant_id=2), connection=request)

    app = Starlette(routes=[Route("/mcp", endpoint, methods=["POST"])])

    async def call(origin):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=origin) as client:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            }
            headers = {"accept": "application/json, text/event-stream", "origin": origin}
            response = await client.post("/mcp", json=payload, headers=headers)
            assert response.status_code == 200, response.text
            payload.update(method="tools/list", params={})
            response = await client.post("/mcp", json=payload, headers=headers)
            assert response.status_code == 200, response.text
            payload.update(method="tools/call", params={"name": "echo", "arguments": {}})
            response = await client.post("/mcp", json=payload, headers=headers)
            assert response.status_code == 200 and not response.json()["result"].get("isError", False), response.text
            payload.update(method="resources/list", params={})
            response = await client.post("/mcp", json=payload, headers=headers)
            assert response.json()["result"]["resources"][0]["name"] == "test"
            payload.update(method="resources/read", params={"uri": "bisheng-skill://2/9/" + "a" * 64})
            assert (await client.post("/mcp", json=payload, headers=headers)).status_code == 200
            headers["origin"] = "https://evil.example"
            assert (await client.post("/mcp", json=payload, headers=headers)).status_code == 403
            headers.pop("origin")
            assert (await client.post("/mcp", json=payload, headers=headers)).status_code == 200

    async with manager.run():
        await asyncio.gather(*(call(origin) for origin in ["http://one.example:3001", "https://two.example:8443"] * 3))
    assert manager.settings.platform_public_url is None
