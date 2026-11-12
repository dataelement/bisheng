"""Temporary SSRF admission: reject before download or tool execution."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.main import handle_http_exception
from bisheng.tool.api import tool as module


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
    assert response.json()["status_code"] == 15033
    assert "SECRET" not in response.text


async def test_super_admin_schema_denial_is_sanitized(api, monkeypatch):
    import socket

    api.super_admin = True
    monkeypatch.setattr(module.ToolServices, "parse_openapi_schema", staticmethod(api.real_parse))
    monkeypatch.setattr(socket.socket, "connect", lambda *_a, **_k: pytest.fail("Forbidden connection attempted"))
    response = await post(api, "schema", {"download_url": "http://127.0.0.1/private?token=SECRET"})
    assert response.json()["status_code"] == 15020
    assert "SECRET" not in response.text
