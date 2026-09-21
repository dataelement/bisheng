import json
from contextlib import asynccontextmanager

import httpx
import pytest
from mcp import types

from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)
from bisheng.open_mcp.contracts import ResourceListData
from bisheng.open_mcp.server import MCP_PATH, OpenMcpDispatchMiddleware, create_open_mcp_runtime


def _principal(*, scopes=frozenset({"knowledge:read", "knowledge:write"})):
    return OpenApiPrincipal(
        credential_id=1,
        actor_kind="service_account",
        actor_id=2,
        actor_name="f067-service",
        tenant_id=3,
        resource_owner_user_id=2,
        scopes=scopes,
        authorization_subject_type="service_account",
        authorization_subject_id=2,
        effective_user_id=None,
    )


def _handler(runtime, request_type):
    return runtime.manager.app.request_handlers[request_type]


def _tool_payload(result):
    return json.loads(result.root.content[0].text)


@pytest.mark.asyncio
async def test_list_tools_returns_only_principal_visible_tools():
    runtime = create_open_mcp_runtime()
    token = set_current_open_api_principal(_principal(scopes=frozenset({"knowledge:read"})))
    try:
        result = await _handler(runtime, types.ListToolsRequest)(types.ListToolsRequest())
    finally:
        reset_current_open_api_principal(token)

    assert {tool.name for tool in result.root.tools} == {
        "bisheng_knowledge_list",
        "bisheng_knowledge_retrieve",
        "bisheng_knowledge_file_list",
    }


@pytest.mark.asyncio
async def test_call_tool_success_returns_structured_result_and_audits(monkeypatch):
    runtime = create_open_mcp_runtime()
    audits = []

    async def _execute(name, arguments):
        assert name == "bisheng_knowledge_list"
        assert arguments == {"type": 0}
        return ResourceListData(data=[], page_size=10, has_more=False)

    monkeypatch.setattr("bisheng.open_mcp.server.execute_tool", _execute)
    monkeypatch.setattr(
        "bisheng.open_mcp.server.open_api_call_audit_service.enqueue",
        audits.append,
    )
    token = set_current_open_api_principal(_principal())
    try:
        result = await _handler(runtime, types.CallToolRequest)(
            types.CallToolRequest(
                params=types.CallToolRequestParams(
                    name="bisheng_knowledge_list",
                    arguments={"type": 0},
                )
            )
        )
    finally:
        reset_current_open_api_principal(token)

    assert result.root.isError is False
    assert result.root.structuredContent == {"data": [], "page_size": 10, "has_more": False, "next_cursor": None}
    assert _tool_payload(result) == result.root.structuredContent
    assert len(audits) == 1
    audit = audits[0]
    assert audit.target_type == "mcp_tool"
    assert audit.target_id == "bisheng_knowledge_list"
    assert audit.tenant_id == 3
    assert audit.audit_metadata["channel"] == "mcp"
    assert audit.audit_metadata["result"] == "success"
    assert audit.audit_metadata["scope"] == "knowledge:read"


@pytest.mark.asyncio
async def test_call_tool_denied_by_scope_does_not_execute_and_audits_error(monkeypatch):
    runtime = create_open_mcp_runtime()
    audits = []

    async def _unexpected_execute(name, arguments):
        raise AssertionError("denied tool must not execute")

    monkeypatch.setattr("bisheng.open_mcp.server.execute_tool", _unexpected_execute)
    monkeypatch.setattr(
        "bisheng.open_mcp.server.open_api_call_audit_service.enqueue",
        audits.append,
    )
    token = set_current_open_api_principal(_principal(scopes=frozenset({"knowledge:read"})))
    try:
        result = await _handler(runtime, types.CallToolRequest)(
            types.CallToolRequest(
                params=types.CallToolRequestParams(
                    name="bisheng_knowledge_delete",
                    arguments={"knowledge_id": 67},
                )
            )
        )
    finally:
        reset_current_open_api_principal(token)

    assert result.root.isError is True
    assert _tool_payload(result)["error"]["code"] == "PERMISSION_DENIED"
    assert audits[0].audit_metadata["error_code"] == "PERMISSION_DENIED"
    assert audits[0].audit_metadata["result"] == "failed"


@pytest.mark.asyncio
async def test_call_tool_validation_error_is_mcp_tool_error(monkeypatch):
    runtime = create_open_mcp_runtime()
    monkeypatch.setattr("bisheng.open_mcp.server.open_api_call_audit_service.enqueue", lambda _: None)
    token = set_current_open_api_principal(_principal())
    try:
        result = await _handler(runtime, types.CallToolRequest)(
            types.CallToolRequest(
                params=types.CallToolRequestParams(
                    name="bisheng_knowledge_delete",
                    arguments={"knowledge_id": 0},
                )
            )
        )
    finally:
        reset_current_open_api_principal(token)

    assert result.root.isError is True
    assert _tool_payload(result)["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_call_tool_unknown_name_is_rejected_by_mcp_protocol_before_execution(monkeypatch):
    runtime = create_open_mcp_runtime()
    audits = []
    monkeypatch.setattr(
        "bisheng.open_mcp.server.open_api_call_audit_service.enqueue",
        audits.append,
    )
    token = set_current_open_api_principal(_principal())
    try:
        result = await _handler(runtime, types.CallToolRequest)(
            types.CallToolRequest(
                params=types.CallToolRequestParams(name="not_allowlisted", arguments={})
            )
        )
    finally:
        reset_current_open_api_principal(token)

    assert result.code == -32602
    assert result.message == "Unknown tool"
    assert audits == []


@pytest.mark.asyncio
async def test_dispatch_middleware_matches_exact_path_and_optional_trailing_slash():
    calls = []

    async def app(scope, receive, send):
        calls.append(("app", scope["path"]))

    async def mcp_app(scope, receive, send):
        calls.append(("mcp", scope["path"]))

    middleware = OpenMcpDispatchMiddleware(app, mcp_app=mcp_app)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        return None

    for path in (MCP_PATH, f"{MCP_PATH}/", f"{MCP_PATH}/nested", "/api/v2/filelib/"):
        await middleware({"type": "http", "path": path}, receive, send)

    assert calls == [
        ("mcp", MCP_PATH),
        ("mcp", f"{MCP_PATH}/"),
        ("app", f"{MCP_PATH}/nested"),
        ("app", "/api/v2/filelib/"),
    ]


@pytest.mark.asyncio
async def test_real_streamable_http_initialize_then_stateless_list(monkeypatch):
    principal = _principal()

    @asynccontextmanager
    async def _authenticated(**kwargs):
        token = set_current_open_api_principal(principal)
        try:
            yield principal
        finally:
            reset_current_open_api_principal(token)

    monkeypatch.setattr("bisheng.open_mcp.auth.open_api_access_context", _authenticated)
    runtime = create_open_mcp_runtime()
    headers = {"Accept": "application/json, text/event-stream"}
    transport = httpx.ASGITransport(app=runtime.app)
    async with runtime.lifespan(), httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
    ) as client:
        initialized = await client.post(
            MCP_PATH,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "f067-test", "version": "1"},
                },
            },
        )
        listed = await client.post(
            MCP_PATH,
            headers={**headers, "MCP-Protocol-Version": "2025-11-25"},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )

    assert initialized.status_code == 200
    assert initialized.json()["result"]["protocolVersion"] == "2025-11-25"
    assert listed.status_code == 200
    assert len(listed.json()["result"]["tools"]) == 10
