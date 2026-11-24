"""Temporary SSRF admission: reject before download or tool execution."""

from secrets import token_urlsafe
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.main import handle_http_exception
from bisheng.tool.api import tool as module
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services import test_openapi
from bisheng_langchain.utils.egress_policy import DestinationDenied


@pytest.fixture
def api(monkeypatch):
    state = SimpleNamespace(
        super_admin=False,
        real_factory=module.TestOpenApiTools.get_api_tool,
        real_parse=module.ToolServices.parse_openapi_schema,
    )
    app = FastAPI()
    app.include_router(module.router, prefix="/api/v1")
    app.add_exception_handler(BaseErrorCode, handle_http_exception)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: UserPayload(
        user_id=2, user_name="fixture", tenant_id=1, user_role=[], is_global_super=state.super_admin
    )
    state.parse = AsyncMock(return_value={"name": "fixture"})
    monkeypatch.setattr(module.ToolServices, "parse_openapi_schema", state.parse)
    state.execute = AsyncMock(return_value="fixture response")
    monkeypatch.setattr(
        module.TestOpenApiTools, "get_api_tool", lambda *_args, **_kwargs: SimpleNamespace(arun=state.execute)
    )
    state.app = app
    return state


async def post(api, endpoint, body):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
        return await client.post("/api/v1/tool/" + endpoint, json=body)


async def test_normal_user_cannot_execute_temporary_tool(api):
    response = await post(api, "test", {"extra": '{"path":"/","method":"get","parameters":[]}', "request_params": {}})
    assert response.json()["status_code"] == 403
    api.execute.assert_not_awaited()


@pytest.mark.parametrize("with_content", [False, True])
async def test_normal_user_cannot_download_schema(api, with_content):
    body = {"download_url": "http://127.0.0.1/private"}
    if with_content:
        body["file_content"] = "{}"
    response = await post(api, "schema", body)
    assert response.json()["status_code"] == 403
    api.parse.assert_not_awaited()


async def test_normal_user_can_still_parse_content(api):
    response = await post(api, "schema", {"file_content": "{}"})
    assert response.json()["status_code"] == 200
    api.parse.assert_awaited_once_with(None, "{}")


async def test_super_admin_retains_entry_access(api):
    api.super_admin = True
    response = await post(api, "schema", {"download_url": "https://example.com/schema"})
    assert response.json()["status_code"] == 200
    response = await post(api, "test", {"extra": '{"path":"/","method":"get","parameters":[]}', "request_params": {}})
    assert response.json()["status_code"] == 200
    api.execute.assert_awaited_once()


async def test_super_admin_cannot_bypass_destination_policy(api, monkeypatch):
    import socket

    api.super_admin = True
    monkeypatch.setattr(module.TestOpenApiTools, "get_api_tool", api.real_factory)
    monkeypatch.setattr(socket.socket, "connect", lambda *_a, **_k: pytest.fail("Forbidden connection attempted"))
    response = await post(
        api,
        "test",
        {
            "server_host": "http://127.0.0.1",
            "extra": '{"path":"/private?token=SECRET","method":"get","parameters":[]}',
            "request_params": {},
        },
    )
    assert response.json()["status_code"] == 15037
    assert "SECRET" not in response.text


async def test_super_admin_schema_denial_is_sanitized(api, monkeypatch):
    import socket

    api.super_admin = True
    monkeypatch.setattr(module.ToolServices, "parse_openapi_schema", staticmethod(api.real_parse))
    monkeypatch.setattr(socket.socket, "connect", lambda *_a, **_k: pytest.fail("Forbidden connection attempted"))
    response = await post(api, "schema", {"download_url": "http://127.0.0.1/private?token=SECRET"})
    assert response.json()["status_code"] == 15020
    assert "SECRET" not in response.text


@pytest.fixture
def saved_tool(api, monkeypatch):
    api.super_admin = True
    parent = SimpleNamespace(
        id=4,
        tenant_id=1,
        is_preset=0,
        is_delete=0,
        server_host="https://tools.example",
        auth_method=1,
        auth_type="bearer",
        api_key=token_urlsafe(16),
        extra="{}",
    )
    operation = SimpleNamespace(
        id=7,
        type=4,
        tenant_id=1,
        is_preset=0,
        is_delete=0,
        extra={
            "path": "/search",
            "method": "post",
            "parameters": [
                {"name": "query", "in": "query", "schema": {"type": "string"}},
            ],
        },
    )
    load_parent = AsyncMock(return_value=parent)
    monkeypatch.setattr(GptsToolsDao, "aget_one_tool_type", load_parent)
    monkeypatch.setattr(GptsToolsDao, "aget_one_tool", AsyncMock(return_value=operation))
    monkeypatch.setattr(test_openapi, "get_current_tenant_id", lambda: 1)
    authorize = AsyncMock()
    monkeypatch.setattr(test_openapi, "require_business_action", authorize)
    request = AsyncMock(return_value=SimpleNamespace(text=lambda: f"echo {parent.api_key}"))
    monkeypatch.setattr(test_openapi.safe_http, "arequest", request)
    return SimpleNamespace(
        parent=parent, operation=operation, load_parent=load_parent, authorize=authorize, request=request
    )


async def test_saved_tool_uses_authorized_saved_configuration_and_masks_response(api, saved_tool):
    response = await post(
        api,
        "4/operations/7/test",
        {
            "request_params": {"query": "term"},
            "server_host": "https://other.example",
            "api_key": "unused",
        },
    )
    assert response.json()["status_code"] == 200
    assert response.json()["data"] == "echo ********"
    saved_tool.authorize.assert_awaited_once_with(ANY, resource_type="tool", resource_id=4, action="edit")
    saved_tool.request.assert_awaited_once_with(
        "POST",
        "https://tools.example/search",
        headers={"Authorization": f"Bearer {saved_tool.parent.api_key}"},
        params={"query": "term"},
        json={},
        timeout=30,
    )


@pytest.mark.parametrize("reason", ["non_admin", "no_edit", "other_tenant", "other_tool"])
async def test_saved_tool_denies_access_before_sending_request(api, saved_tool, reason):
    if reason == "non_admin":
        api.super_admin = False
    elif reason == "no_edit":
        saved_tool.authorize.side_effect = UnAuthorizedError()
    elif reason == "other_tenant":
        saved_tool.parent.tenant_id = 2
    else:
        saved_tool.operation.type = 5

    response = await post(api, "4/operations/7/test", {"request_params": {}})
    assert response.json()["status_code"] == (403 if reason in {"non_admin", "no_edit"} else 404)
    saved_tool.request.assert_not_awaited()
    if reason == "non_admin":
        saved_tool.load_parent.assert_not_awaited()


async def test_saved_tool_uses_saved_custom_query_authentication(api, saved_tool):
    saved_tool.parent.auth_type = "custom"
    saved_tool.parent.extra = '{"api_location":"query","parameter_name":"token"}'

    response = await post(api, "4/operations/7/test", {"request_params": {"query": "term"}})

    assert response.json()["status_code"] == 200
    assert saved_tool.request.await_args.kwargs["headers"] == {}
    assert saved_tool.request.await_args.kwargs["params"] == {"query": "term", "token": saved_tool.parent.api_key}


async def test_saved_tool_preserves_destination_policy_errors(api, saved_tool):
    saved_tool.request.side_effect = DestinationDenied()

    response = await post(api, "4/operations/7/test", {"request_params": {}})

    assert response.json()["status_code"] == 15037
