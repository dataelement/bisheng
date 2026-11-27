"""Personal tokens must have the same capabilities and authorization over HTTP and over MCP.

HTTP: an endpoint is callable by a personal token only if its ``open_api_scope(..., pat=True)`` marker says so.
MCP: a tool is visible to and callable by a personal token only if its registry entry has ``allow_pat=True``.
These two lists are maintained in different files, so this test fails whenever they drift apart.
"""

from unittest.mock import AsyncMock

import pytest
from mcp import types

from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.scopes import get_open_api_scope_marker
from bisheng.open_endpoints.api.endpoints import filelib, knowledge, knowledge_answer
from bisheng.open_mcp import server as mcp_server
from bisheng.open_mcp.registry import TOOL_DEFINITIONS, TOOL_REGISTRY, list_tools_for

API_PREFIX = "/api/v2"


def _http_endpoints():
    """(method, path) -> marker for every v2 endpoint that carries an open API marker."""
    found = {}
    for module in (filelib, knowledge, knowledge_answer):
        for route in module.router.routes:
            marker = get_open_api_scope_marker(route.endpoint)
            if marker is None:
                continue
            for method in route.methods - {"HEAD", "OPTIONS"}:
                found[(method, API_PREFIX + route.path)] = marker
    return found


def _principal(*, actor_kind, scopes=frozenset({"knowledge:read", "knowledge:write"})):
    natural_person = actor_kind == "natural_person"
    return OpenApiPrincipal(
        credential_id=1,
        actor_kind=actor_kind,
        actor_id=2,
        actor_name="caller",
        tenant_id=3,
        resource_owner_user_id=2,
        scopes=scopes,
        authorization_subject_type="user" if natural_person else "service_account",
        authorization_subject_id=2,
        effective_user_id=2 if natural_person else None,
    )


def test_every_tool_maps_to_a_real_http_endpoint():
    endpoints = _http_endpoints()
    for tool in TOOL_DEFINITIONS:
        assert (tool.source_method, tool.source_route) in endpoints, tool.name


def test_personal_token_http_and_mcp_expose_exactly_the_same_capabilities():
    http_allowed = {key for key, marker in _http_endpoints().items() if marker.pat_allowed}
    mcp_allowed = {(tool.source_method, tool.source_route) for tool in TOOL_DEFINITIONS if tool.allow_pat}

    assert http_allowed == mcp_allowed


def test_personal_token_tools_and_endpoints_require_the_same_scope_and_modes():
    endpoints = _http_endpoints()
    for tool in TOOL_DEFINITIONS:
        marker = endpoints[(tool.source_method, tool.source_route)]
        assert marker.scope == tool.scope, tool.name
        assert marker.modes == tool.modes, tool.name


def test_personal_token_may_write_but_never_delete():
    """个人令牌带读和写权限位：可以创建、更新、上传，删除类始终不开放。"""
    destructive = {"bisheng_knowledge_delete", "bisheng_knowledge_clear",
                  "bisheng_knowledge_file_delete", "bisheng_knowledge_files_delete"}
    allowed = [tool for tool in TOOL_DEFINITIONS if tool.allow_pat]
    assert {tool.name for tool in allowed} & destructive == set()
    assert {"bisheng_knowledge_create", "bisheng_knowledge_update", "bisheng_knowledge_file_upload"} <= {
        tool.name for tool in allowed
    }
    for key, marker in _http_endpoints().items():
        if marker.pat_allowed:
            assert marker.scope in ("knowledge:read", "knowledge:write"), key


def test_personal_token_discovers_only_what_http_allows():
    http_allowed = {key for key, marker in _http_endpoints().items() if marker.pat_allowed}
    visible = {
        (TOOL_REGISTRY[tool.name].source_method, TOOL_REGISTRY[tool.name].source_route)
        for tool in list_tools_for(_principal(actor_kind="natural_person"))
    }

    assert visible == http_allowed
    assert len(visible) == 6


def test_personal_token_sees_read_and_write_but_no_destructive_tool():
    visible = {tool.name for tool in list_tools_for(_principal(actor_kind="natural_person"))}
    assert visible == {
        "bisheng_knowledge_list",
        "bisheng_knowledge_file_list",
        "bisheng_knowledge_retrieve",
        "bisheng_knowledge_create",
        "bisheng_knowledge_update",
        "bisheng_knowledge_file_upload",
    }


@pytest.mark.parametrize("tool_name", sorted(tool.name for tool in TOOL_DEFINITIONS if not tool.allow_pat))
def test_personal_token_cannot_call_a_hidden_tool_even_by_name(tool_name):
    definition = TOOL_REGISTRY[tool_name]
    assert not definition.visible_to(_principal(actor_kind="natural_person"))
    assert not definition.visible_to(_principal(actor_kind="natural_person", scopes=frozenset({"knowledge:read"})))


@pytest.mark.asyncio
async def test_calling_a_hidden_tool_with_a_personal_token_never_executes_it(monkeypatch):
    from bisheng.open_api.domain.context import reset_current_open_api_principal, set_current_open_api_principal

    runtime = mcp_server.create_open_mcp_runtime()
    execute = AsyncMock()
    monkeypatch.setattr(mcp_server, "execute_tool", execute)
    token = set_current_open_api_principal(_principal(actor_kind="natural_person"))
    try:
        handler = runtime.manager.app.request_handlers[types.CallToolRequest]
        result = await handler(
            types.CallToolRequest(
                method="tools/call",
                params=types.CallToolRequestParams(name="bisheng_knowledge_delete", arguments={"knowledge_id": 1}),
            )
        )
    finally:
        reset_current_open_api_principal(token)

    assert result.root.isError is True
    assert "PERMISSION_DENIED" in result.root.content[0].text
    execute.assert_not_awaited()
