from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from starlette.applications import Starlette

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.developer_token import (
    DeveloperTokenDisabledError,
    DeveloperTokenInvalidError,
    DeveloperTokenIpForbiddenError,
    DeveloperTokenLimiterUnavailableError,
    DeveloperTokenMissingError,
    DeveloperTokenRateLimitedError,
    DeveloperTokenRouteForbiddenError,
)
from bisheng.core.config.settings import McpConf, McpServerConf
from bisheng.core.context.tenant import (
    _admin_scope_tenant_id,
    _bypass_tenant_filter,
    current_tenant_id,
    get_current_tenant_id,
    get_visible_tenant_ids,
    is_tenant_filter_bypassed,
    visible_tenant_ids,
)
from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.developer_token.domain.services import DeveloperTokenService
from bisheng.mcp_server.api.router import McpServerApp, mcp_routes
from bisheng.open_endpoints.domain.schemas.filelib import RetrieveChunk, RetrieveResp


@asynccontextmanager
async def server(monkeypatch, *, enabled=True, failure=None, search=None):
    """AC-01-10, AC-12: real SDK and HTTP with controlled business dependencies."""
    calls = []
    active = set()

    async def authenticate(raw_token, **kwargs):
        assert kwargs["require_explicit_route"] is True
        assert kwargs["route_path"] == "/mcp"
        if failure:
            raise failure()
        if not raw_token:
            raise DeveloperTokenMissingError()
        user_id = 8 if raw_token == "second" else 7
        return DeveloperTokenPrincipal(
            token_id=user_id,
            tenant_id=user_id,
            user=UserPayload(user_id=user_id, user_name="bound", user_role=[2], tenant_id=user_id),
        )

    monkeypatch.setattr(DeveloperTokenService, "authenticate_principal", authenticate)

    @asynccontextmanager
    async def factory(request, user):
        active.add(user.user_id)

        async def retrieve(req):
            assert not is_tenant_filter_bypassed()
            calls.append((user.user_id, get_current_tenant_id(), get_visible_tenant_ids(), req.query))
            if search:
                return await search(req)
            return RetrieveResp(
                chunks=[
                    RetrieveChunk(
                        content="authorized content",
                        knowledge_id=118,
                        document_id=1,
                        document_name="document",
                        chunk_index=0,
                    )
                ],
                total=1,
            )

        try:
            yield SimpleNamespace(retrieve=retrieve, timeout_seconds=1.0)
        finally:
            active.remove(user.user_id)

    runtime = McpServerApp(
        config_provider=AsyncMock(return_value=McpServerConf(enabled=enabled)),
        search_factory=factory,
    )
    app = Starlette(routes=mcp_routes(runtime))
    async with runtime.lifespan():
        yield app, calls, active


@asynccontextmanager
async def session(app, token="first", path="/mcp"):
    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)

    async with streamablehttp_client(
        "http://localhost" + path,
        headers={"X-Developer-Token": token},
        httpx_client_factory=client_factory,
    ) as (read, write, _):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=5)) as client:
            await client.initialize()
            yield client


async def test_disabled_server_does_not_authenticate(monkeypatch):
    """AC-01: disabled route is inert and returns a real 404."""
    async with server(monkeypatch, enabled=False, failure=RuntimeError) as (app, calls, _):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            response = await client.post("http://localhost/mcp", json={})
        assert response.status_code == 404
        assert not calls


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (DeveloperTokenMissingError, 401, 19801),
        (DeveloperTokenInvalidError, 401, 19802),
        (DeveloperTokenDisabledError, 401, 19803),
        (DeveloperTokenIpForbiddenError, 403, 19804),
        (DeveloperTokenRouteForbiddenError, 403, 19812),
        (DeveloperTokenRateLimitedError, 429, 19805),
        (DeveloperTokenLimiterUnavailableError, 503, 19806),
    ],
)
async def test_auth_failures_have_real_http_status(monkeypatch, failure, status, code):
    """AC-03-05: authentication fails before business resources are acquired."""
    async with server(monkeypatch, failure=failure) as (app, calls, active):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            response = await client.post("http://localhost/mcp", json={})
        assert response.status_code == status
        assert response.json()["status_code"] == code
        assert not calls and not active


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
async def test_sdk_lists_and_calls_only_search_knowledge(monkeypatch, path):
    """AC-02, AC-06, AC-10: native handshake, flat schema, result and identity."""
    async with server(monkeypatch) as (app, calls, active):
        async with session(app, path=path) as client:
            tools = (await client.list_tools()).tools
            assert [tool.name for tool in tools] == ["search_knowledge"]
            assert tools[0].inputSchema["additionalProperties"] is False
            assert "external_id" not in tools[0].inputSchema["properties"]
            assert tools[0].outputSchema["properties"]["chunks"]
            result = await client.call_tool("search_knowledge", {"query": " query ", "knowledge_base_ids": [118]})
            assert not result.isError
            assert result.structuredContent["chunks"][0]["content"] == "authorized content"
            assert result.structuredContent["total"] == 1
        assert calls == [(7, 7, frozenset({7}), "query")]
        assert not active


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "q", "knowledge_base_ids": [118], "external_id": "admin"},
        {"query": "q", "knowledge_base_ids": [118], "user_id": 1},
        {"query": "q", "knowledge_base_ids": [118], "tenant_id": 1},
        {"query": "  ", "knowledge_base_ids": [118]},
        {"query": "q", "knowledge_base_ids": [0]},
        {"query": "q", "knowledge_base_ids": [118], "top_k": 51},
    ],
)
async def test_sdk_rejects_invalid_or_identity_parameters(monkeypatch, arguments):
    """AC-08: SDK schema and execution both deny invalid/extra arguments."""
    async with server(monkeypatch) as (app, calls, active):
        async with session(app) as client:
            result = await client.call_tool("search_knowledge", arguments)
            assert result.isError
        assert not calls and not active


async def test_unknown_tool_cannot_run_business(monkeypatch):
    """AC-08: only the explicitly registered tool is callable."""
    async with server(monkeypatch) as (app, calls, _):
        async with session(app) as client:
            assert (await client.call_tool("invoke_workflow", {})).isError
        assert not calls


@pytest.mark.parametrize("empty", [True, False])
async def test_empty_results_and_sanitized_failure(monkeypatch, empty):
    """AC-06, AC-09: empty success and business failure remain distinct."""

    async def retrieve(req):
        if empty:
            return RetrieveResp(chunks=[], total=0)
        raise RuntimeError("sensitive database connection")

    async with server(monkeypatch, search=retrieve) as (app, _, active):
        async with session(app) as client:
            result = await client.call_tool("search_knowledge", {"query": "q", "knowledge_base_ids": [118]})
            assert result.isError is not empty
            if empty:
                assert result.structuredContent == {"chunks": [], "total": 0}
            else:
                assert "sensitive" not in str(result)
        assert not active


async def test_concurrent_requests_and_cancel_restore_context(monkeypatch):
    """AC-10: actual SDK tasks isolate users; cancelled HTTP closes business scope."""
    started = asyncio.Event()

    async def retrieve(req):
        if req.query == "cancel":
            started.set()
            await asyncio.Event().wait()
        await asyncio.sleep(0.01)
        return RetrieveResp(chunks=[], total=0)

    async with server(monkeypatch, search=retrieve) as (app, calls, active):

        async def run(token):
            async with session(app, token) as client:
                return await client.call_tool("search_knowledge", {"query": "q", "knowledge_base_ids": [118]})

        results = await asyncio.gather(run("first"), run("second"))
        assert all(not result.isError for result in results)
        assert {(row[0], row[1], row[2]) for row in calls} == {
            (7, 7, frozenset({7})),
            (8, 8, frozenset({8})),
        }
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            task = asyncio.create_task(
                client.post(
                    "http://localhost/mcp",
                    headers={"X-Developer-Token": "first", "Accept": "application/json, text/event-stream"},
                    json={
                        "jsonrpc": "2.0",
                        "id": 9,
                        "method": "tools/call",
                        "params": {
                            "name": "search_knowledge",
                            "arguments": {"query": "cancel", "knowledge_base_ids": [118]},
                        },
                    },
                )
            )
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert not active


@pytest.mark.parametrize(
    ("url", "headers"),
    [
        ("http://untrusted.example/mcp", {}),
        ("http://localhost/mcp", {"Origin": "https://untrusted.example"}),
    ],
)
async def test_transport_accepts_any_host_or_origin_with_token(monkeypatch, url, headers):
    """AC-12: authorized clients no longer need Host/Origin configuration."""
    async with server(monkeypatch) as (app, calls, active):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            response = await client.post(
                url,
                headers={
                    "X-Developer-Token": "first",
                    "Accept": "application/json, text/event-stream",
                    **headers,
                },
                json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            )
        assert response.status_code == 200
        assert response.json()["result"] == {}
        assert not calls and not active


@pytest.mark.parametrize(
    "config", [{}, {"enable_stdio": False}, {"server": {}}, {"server": {"allowed_hosts": [], "allowed_origins": ["*"]}}]
)
def test_missing_or_legacy_server_config_defaults_to_enabled(config):
    """AC-01: old allowlist fields are ignored and an explicit off switch is retained."""
    conf = McpConf.model_validate(config)
    assert conf.server.enabled
    assert McpConf.model_validate({"server": {"enabled": False}}).server.enabled is False


async def test_unsupported_http_methods_require_authentication(monkeypatch):
    """AC-04, AC-12: no unauthenticated GET stream or DELETE session endpoint."""
    async with server(monkeypatch) as (app, calls, active):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            missing = await client.get("http://localhost/mcp")
            allowed = await client.get("http://localhost/mcp", headers={"X-Developer-Token": "first"})
            assert missing.status_code == 401
            assert allowed.status_code == 405
        assert not calls and not active


async def test_tool_timeout_is_error_and_releases_resources(monkeypatch):
    """AC-09, AC-10: retrieval deadline is observable and cleans the business scope."""

    async def retrieve(req):
        await asyncio.sleep(2)

    async with server(monkeypatch, search=retrieve) as (app, _, active):
        async with session(app) as client:
            result = await client.call_tool("search_knowledge", {"query": "q", "knowledge_base_ids": [118]})
            assert result.isError
            assert "timed out" in result.content[0].text
        assert not active


async def test_inherited_admin_context_cannot_bypass_token_identity(monkeypatch):
    """AC-10: SDK business tasks clear inherited management/bypass state and restore it."""
    values = (
        (current_tenant_id, 999),
        (visible_tenant_ids, frozenset({999})),
        (_admin_scope_tenant_id, 999),
        (_bypass_tenant_filter, True),
    )
    tokens = [(var, var.set(value)) for var, value in values]
    try:
        async with server(monkeypatch) as (app, calls, active):
            async with session(app) as client:
                result = await client.call_tool("search_knowledge", {"query": "q", "knowledge_base_ids": [118]})
                assert not result.isError
            assert calls == [(7, 7, frozenset({7}), "q")]
            assert not active
        assert get_current_tenant_id() == 999
        assert get_visible_tenant_ids() == frozenset({999})
        assert is_tenant_filter_bypassed()
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
