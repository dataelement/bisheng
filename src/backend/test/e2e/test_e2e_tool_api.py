"""Tool API contract through the actual service and executor; no save/publish flow."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.api.endpoints import tools
from bisheng.dsh.domain.services.tools import ToolInvocationService
from bisheng.dsh.tool_runtime import get_tool_service
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services import bounded_openapi, executor
from bisheng.tool.domain.services.saved_tools import SavedToolService
from test.dsh.test_access import service as access_service
from test.dsh.test_access import token

TOOL_KEY = "tool_type_7_example"


@pytest.fixture
def api(monkeypatch):
    # Model the existing tool lookup; tool creation/storage is outside this API.
    parameters = [{"name": "amount", "in": "body", "required": True, "schema": {"type": "integer"}}]
    schema = {"type": "object", "properties": {"amount": {"type": "integer"}}, "required": ["amount"]}
    document = {
        "openapi": "3.0.3",
        "paths": {
            "/convert": {
                "post": {"operationId": "convert", "requestBody": {"content": {"application/json": {"schema": schema}}}}
            }
        },
    }
    tool = SimpleNamespace(
        id=7,
        type=7,
        tool_key=TOOL_KEY,
        name="convert",
        desc="API fixture",
        tenant_id=2,
        is_delete=0,
        is_preset=0,
        extra=json.dumps({"path": "/convert", "method": "post", "parameters": parameters}),
    )
    category = SimpleNamespace(
        id=7,
        tenant_id=2,
        is_delete=0,
        is_preset=0,
        openapi_schema=json.dumps(document),
        server_host="https://tool.example",
        extra="{}",
        auth_method=0,
        auth_type="basic",
        api_key=None,
    )
    state = SimpleNamespace(
        tool=tool, category=category, allowed=True, status=200, received=[], result={"converted": 6}
    )
    permission = AsyncMock(side_effect=lambda *_args, **_kwargs: state.allowed)
    state.permission = permission

    async def user(user_id, tenant_id):
        from bisheng.common.dependencies.user_deps import UserPayload

        return UserPayload(
            user_id=user_id, user_name="tester", user_role=[], tenant_id=tenant_id, is_global_super=False
        )

    def upstream(request):
        state.received.append((request.url.path, json.loads(request.content)))
        return httpx.Response(state.status, json=state.result)

    client_factory = httpx.AsyncClient
    monkeypatch.setattr(
        bounded_openapi,
        "httpx",
        SimpleNamespace(
            AsyncClient=lambda **kwargs: client_factory(transport=httpx.MockTransport(upstream), **kwargs),
            TimeoutException=httpx.TimeoutException,
            HTTPError=httpx.HTTPError,
        ),
    )
    monkeypatch.setattr(executor.ToolExecutor, "_build_permission_user", staticmethod(user))
    monkeypatch.setattr(executor, "check_business_action", permission)
    monkeypatch.setattr(
        GptsToolsDao, "aget_tool_by_tool_key", AsyncMock(side_effect=lambda key: tool if key == tool.tool_key else None)
    )
    monkeypatch.setattr(GptsToolsDao, "aget_one_tool_type", AsyncMock(return_value=category))
    monkeypatch.setattr(executor.telemetry_service, "log_event", AsyncMock())
    state.leases = SimpleNamespace(acquire=AsyncMock(return_value="owner"), release=AsyncMock())
    service = ToolInvocationService(SavedToolService(), state.leases)
    app = FastAPI()
    app.include_router(tools.router, prefix="/api/v1")
    app.dependency_overrides[get_runtime] = lambda: SimpleNamespace(access=access_service())
    app.dependency_overrides[get_tool_service] = lambda: service
    state.app, state.headers = app, {"Authorization": "Bearer " + token()}
    return state


@pytest.mark.parametrize("field,scalar,value", [("amount", "integer", 3), ("query", "string", " hello ")])
async def test_api_executes_existing_tool(api, field, scalar, value):
    """AC-01, AC-15, AC-17, AC-23: direct call, saved arguments and generic result."""
    operation = json.loads(api.category.openapi_schema)
    operation["paths"]["/convert"]["post"]["requestBody"]["content"]["application/json"]["schema"] = {
        "type": "object",
        "properties": {field: {"type": scalar}},
        "required": [field],
    }
    api.category.openapi_schema = json.dumps(operation)
    api.tool.extra = json.dumps(
        {
            "path": "/convert",
            "method": "post",
            "parameters": [{"name": field, "in": "body", "required": True, "schema": {"type": scalar}}],
        }
    )
    # Category metadata cannot replace the validated operation.
    api.category.extra = json.dumps({"path": "/wrong", "parameters": [], "method": "get"})
    api.tool.tool_key = "bs_web_search"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/dsh/tools/bs_web_search/invoke", headers=api.headers, json={"arguments": {field: value}}
        )
    assert response.status_code == 200
    assert response.json() == {"tool": "bs_web_search", "result": {"converted": 6}}
    assert api.received == [("/convert", {field: value})]
    api.permission.assert_awaited_once()
    api.leases.release.assert_awaited_once_with(2, "bs_web_search", "owner")


@pytest.mark.parametrize(
    "case,status,code",
    [
        ("forged", 401, "invalid_access_token"),
        ("denied", 403, "tool_permission_denied"),
        ("missing", 404, "tool_not_found"),
        ("deleted", 404, "tool_not_found"),
        ("tenant", 404, "tool_not_found"),
        ("parent_tenant", 404, "tool_not_found"),
        ("unsupported", 400, "tool_unsupported"),
        ("arguments", 400, "tool_arguments_invalid"),
        ("upstream", 502, "tool_upstream_failed"),
    ],
)
async def test_api_rejects_invalid_calls(api, case, status, code):
    """AC-05, AC-06, AC-09, AC-11, AC-12, AC-14, AC-19, AC-20: safe API failures."""
    headers, key, arguments = api.headers, TOOL_KEY, {"amount": 3}
    if case == "forged":
        headers = {"Authorization": "Bearer forged"}
    elif case == "denied":
        api.allowed = False
    elif case == "missing":
        key = "missing"
    elif case == "deleted":
        api.tool.is_delete = 1
    elif case == "tenant":
        headers = {"Authorization": "Bearer " + token(tenant_id="3")}
    elif case == "parent_tenant":
        api.category.tenant_id = 3
    elif case == "unsupported":
        api.tool.is_preset = 2
    elif case == "arguments":
        arguments = {"amount": True}
    elif case == "upstream":
        api.status, api.result = 500, {"private": "provider body"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
        response = await client.post(f"/api/v1/dsh/tools/{key}/invoke", headers=headers, json={"arguments": arguments})
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert response.json()["request_id"] and "provider body" not in response.text
    if case == "upstream":
        api.leases.release.assert_awaited_once()
    else:
        assert api.received == []
        api.leases.acquire.assert_not_awaited()


async def test_api_does_not_capture_ambient_traces(api):
    """AC-21: invoking the API must not disclose arguments to inherited callbacks."""
    from langchain_core.runnables.config import var_child_runnable_config
    from langchain_core.tracers.context import collect_runs

    scope = var_child_runnable_config.set({"callbacks": []})
    try:
        with collect_runs() as collector:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
                response = await client.post(
                    f"/api/v1/dsh/tools/{TOOL_KEY}/invoke", headers=api.headers, json={"arguments": {"amount": 3}}
                )
            assert response.status_code == 200 and collector.traced_runs == []
    finally:
        scope.var.reset(scope)
