"""One deployment origin drives browser authorization and the real MCP transport."""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

import httpx
import pytest
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

from bisheng.dsh.config import DshSettings
from bisheng.dsh.domain.services.authorization import DshAuthorizationService
from bisheng.dsh.work_mcp import WorkMcpResponse, create_work_mcp_runtime, work_transport_security

ORIGINS = [
    ("http://192.0.2.15:18081/", "http://192.0.2.15:18081"),
    ("https://Work.Example.COM/", "https://work.example.com"),
    ("https://work.example.com:443", "https://work.example.com"),
    ("http://work.example.com:80/", "http://work.example.com"),
    ("https://work.example.com:18443", "https://work.example.com:18443"),
    ("https://例子.测试/", "https://xn--fsqu00a.xn--0zwm56d"),
    ("http://[2001:0db8:0:0:0:0:0:1]:18081", "http://[2001:db8::1]:18081"),
]


@pytest.mark.parametrize("configured,expected", ORIGINS)
async def test_single_origin_for_login_and_real_mcp(configured, expected, monkeypatch):
    settings = DshSettings(enabled=True, platform_public_url=configured)
    assert settings.platform_public_url == expected
    redis = SimpleNamespace(set=AsyncMock(return_value=True))
    authorization = DshAuthorizationService(redis, settings.platform_public_url)
    payload = {
        "redirect_uri": "http://127.0.0.1:49152/dsh/callback",
        "code_challenge": base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("="),
    }
    result = await authorization.create(SimpleNamespace(**payload, model_dump=lambda: payload))
    assert result["authorize_url"].startswith(expected + "/desktop-login?auth_id=")

    service = SimpleNamespace(
        list_tools=AsyncMock(
            return_value=[
                {
                    "name": "bisheng_tool_7",
                    "description": "Read test data",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ]
        )
    )
    monkeypatch.setattr("bisheng.dsh.work_mcp.WorkCapabilitiesService", lambda user: service)
    manager = create_work_mcp_runtime(work_transport_security(settings.platform_public_url))

    async def endpoint(request: Request):
        return WorkMcpResponse(manager, SimpleNamespace(user_id=42, tenant_id=2))

    app = Starlette(routes=[Route("/api/v1/dsh/work/mcp", endpoint, methods=["POST"])])
    headers = {"accept": "application/json, text/event-stream", "origin": expected}
    async with (
        manager.run(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url=expected,
            headers=headers,
        ) as client,
    ):
        response = await client.post(
            "/api/v1/dsh/work/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "origin-regression", "version": "1"},
                },
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["serverInfo"]["name"] == "bisheng-enterprise-work"
        response = await client.post(
            "/api/v1/dsh/work/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
            },
            headers={"mcp-protocol-version": "2025-11-25"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["tools"][0]["name"] == "bisheng_tool_7"


@pytest.mark.parametrize("configured,expected", ORIGINS)
async def test_host_and_origin_validation_stays_bound_to_config(configured, expected):
    from mcp.server.transport_security import TransportSecurityMiddleware

    policy = TransportSecurityMiddleware(work_transport_security(configured))
    authority = urlsplit(expected).netloc

    def request(host, origin, **extra):
        headers = {"host": host, "origin": origin, "content-type": "application/json", **extra}
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/mcp",
                "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
            }
        )

    assert await policy.validate_request(request(authority, expected), is_post=True) is None
    wrong_host = await policy.validate_request(request("other.example", expected), is_post=True)
    assert wrong_host.status_code == 421
    wrong_origin = await policy.validate_request(request(authority, "https://other.example"), is_post=True)
    assert wrong_origin.status_code == 403
    spoofed = await policy.validate_request(
        request("other.example", expected, **{"x-forwarded-host": authority}),
        is_post=True,
    )
    assert spoofed.status_code == 421


@pytest.mark.parametrize(
    "value",
    [
        "https://work.example/path",
        "https://user:pass@work.example",
        "https://work.example?x=1",
        "https://work.example#x",
        "https://work.example\\other",
        "https://work.example\n",
        " https://work.example",
        "https://work.example:0",
        "https://work.example:65536",
    ],
)
def test_deployment_origin_has_one_unambiguous_http_authority(value):
    with pytest.raises(ValidationError):
        DshSettings(enabled=True, platform_public_url=value)


def test_work_runtime_can_start_without_optional_dsh_origin():
    policy = work_transport_security(None)
    assert policy.enable_dns_rebinding_protection
    assert policy.allowed_hosts == []
    assert policy.allowed_origins == []
    assert create_work_mcp_runtime(policy) is not None
