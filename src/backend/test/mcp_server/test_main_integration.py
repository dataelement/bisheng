import asyncio
import socket
import sys
from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import uvicorn
from fastapi import APIRouter
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from bisheng.api_rate_limit.domain.schemas import ApiRateLimitConfig
from bisheng.api_rate_limit.domain.services import ApiRateLimitService
from bisheng.core.config.openfga import OpenFgaGuardConf
from bisheng.core.config.settings import McpServerConf
from bisheng.mcp_server.api.router import McpServerApp, mcp_routes
from test.mcp_server.test_mcp_server import server


def main_app(monkeypatch):
    # Existing global test stubs break unrelated assistant router inheritance.
    # Keep the real MCP exports and main middleware; isolate other business routes.
    routes = ModuleType("bisheng.api.router")
    routes.router = APIRouter(prefix="/api/v1")
    routes.router_rpc = APIRouter(prefix="/api/v2")
    routes.McpServerApp = McpServerApp
    routes.mcp_routes = mcp_routes
    monkeypatch.setitem(sys.modules, "bisheng.api.router", routes)
    from bisheng import main

    events = []

    async def initialize(**kwargs):
        events.append("initialize")

    async def init_data():
        events.append("defaults")

    async def close():
        events.append("close")

    monkeypatch.setattr(main, "initialize_app_context", initialize)
    monkeypatch.setattr(main, "init_default_data", init_data)
    monkeypatch.setattr(main, "close_app_context", close)
    monkeypatch.setattr(main.thread_pool, "tear_down", Mock())
    # The shared auth import stub is a MagicMock, which Starlette cannot register as an exception class.
    monkeypatch.setattr(main, "AuthJWTException", type("AuthJWTException", (Exception,), {}))
    monkeypatch.setattr(main.settings, "multi_tenant", SimpleNamespace(enabled=False))
    monkeypatch.setattr(main.settings, "debug", False)
    monkeypatch.setattr(ApiRateLimitService, "get_runtime_config", AsyncMock(return_value=ApiRateLimitConfig()))
    monkeypatch.setattr(
        "bisheng.common.middleware.openfga_guard._load_guard_conf",
        AsyncMock(return_value=OpenFgaGuardConf(enabled=False)),
    )
    return main.create_app(), events


@asynccontextmanager
async def network_server(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.setblocking(False)
    url = f"http://127.0.0.1:{sock.getsockname()[1]}/mcp"
    service = uvicorn.Server(uvicorn.Config(app, lifespan="on", access_log=False, log_level="warning"))
    task = asyncio.create_task(service.serve(sockets=[sock]))

    async def started():
        while not service.started:
            if task.done():
                await task
                raise RuntimeError("test server failed to start")
            await asyncio.sleep(0.01)

    try:
        await asyncio.wait_for(started(), 5)
        yield url
    finally:
        service.should_exit = True
        try:
            await asyncio.wait_for(task, 5)
        finally:
            sock.close()


async def test_real_network_sdk_through_main_middleware(monkeypatch):
    """AC-02, AC-03, AC-06, AC-12: actual TCP, SDK, main router and middleware."""
    async with server(monkeypatch) as (fake_app, calls, active):
        app, events = main_app(monkeypatch)
        configured = fake_app.routes[0].endpoint
        runtime = app.state.mcp_server
        runtime.config_provider = configured.config_provider
        runtime.search_service = configured.search_service
        async with network_server(app) as url:
            async with httpx.AsyncClient() as client:
                assert (await client.post(url, json={})).status_code == 401
            async with httpx.AsyncClient(headers={"X-Developer-Token": "first"}) as http_client:
                async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        assert [t.name for t in (await client.list_tools()).tools] == ["search_knowledge"]
                        result = await client.call_tool("search_knowledge", {"query": "q", "knowledge_base_ids": [118]})
                        assert result.structuredContent["total"] == 1
                        assert not result.isError
            assert not active
        assert calls == [(7, 7, frozenset({7}), "q")]
        assert events == ["initialize", "defaults", "close"]
        assert runtime.server is None


async def test_main_startup_failure_cleans_infrastructure(monkeypatch):
    """AC-12: MCP initialization errors do not leak already initialized resources."""
    app, events = main_app(monkeypatch)
    app.state.mcp_server.config_provider = AsyncMock(side_effect=RuntimeError("invalid MCP configuration"))
    with pytest.raises(RuntimeError, match="invalid MCP configuration"):
        async with app.router.lifespan_context(app):
            pytest.fail("startup must fail")
    assert events == ["initialize", "defaults", "close"]
    assert app.state.mcp_server.server is None


async def test_main_shutdown_and_disabled_route(monkeypatch):
    """AC-01, AC-12: missing server configuration leaves the MCP endpoint closed."""
    app, events = main_app(monkeypatch)
    app.state.mcp_server.config_provider = AsyncMock(return_value=McpServerConf())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            assert (await client.post("http://localhost/mcp", json={})).status_code == 404
    assert events == ["initialize", "defaults", "close"]


async def test_real_network_disconnect_closes_tool_scope(monkeypatch):
    """AC-10: a TCP disconnect cancels business work before its retrieval deadline."""
    entered = asyncio.Event()

    async def retrieve(req):
        entered.set()
        await asyncio.Event().wait()

    async with server(monkeypatch, search=retrieve) as (app, _, active):
        async with network_server(app) as url:
            async with httpx.AsyncClient() as client:
                task = asyncio.create_task(
                    client.post(
                        url,
                        headers={"X-Developer-Token": "first", "Accept": "application/json, text/event-stream"},
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/call",
                            "params": {
                                "name": "search_knowledge",
                                "arguments": {"query": "cancel", "knowledge_base_ids": [118]},
                            },
                        },
                    )
                )
                await asyncio.wait_for(entered.wait(), 2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

                async def released():
                    while active:
                        await asyncio.sleep(0.01)

                await asyncio.wait_for(released(), 0.5)
