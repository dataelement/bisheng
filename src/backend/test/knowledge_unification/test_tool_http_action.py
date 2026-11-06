"""The frozen tool query accepts use only as a visibility alias. AC-35/66/79/82/83."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.open_api import PersonalTokenDataScopeError
from bisheng.common.errcode.permission import PermissionInvalidResourceError


@pytest.fixture
def tool_http(monkeypatch):
    from bisheng.tool.api import tool as module

    user = UserPayload(user_id=7, tenant_id=101, user_role=[])
    rows = [{"id": 10, "name": "Visible tool", "children": [], "write": False, "delete": False}]
    listing = AsyncMock(return_value=rows)
    identities = []

    def service(*, login_user):
        identities.append(login_user)
        return SimpleNamespace(get_tool_list=listing)

    monkeypatch.setattr(module, "ToolServices", service)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    return SimpleNamespace(app=app, user=user, rows=rows, listing=listing, identities=identities)


@pytest.mark.parametrize("action", [None, "use", "visible"])
@pytest.mark.parametrize("is_preset", [None, 0, 1, 2])
async def test_tool_query_preserves_filters_identity_and_envelope(tool_http, action, is_preset):
    case = tool_http
    params = {}
    if action is not None:
        params["action"] = action
    if is_preset is not None:
        params["is_preset"] = is_preset
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=case.app), base_url="http://asgi", trust_env=False
    ) as client:
        response = await client.get("/api/v1/tool", params=params)
    assert response.status_code == 200
    assert response.json() == {"status_code": 200, "status_message": "SUCCESS", "data": case.rows}
    case.listing.assert_awaited_once_with(is_preset, "visible")
    assert len(case.identities) == 1 and case.identities[0] is case.user


async def test_tool_openapi_default_is_visible(tool_http):
    operation = tool_http.app.openapi()["paths"]["/api/v1/tool"]["get"]
    parameter = next(item for item in operation["parameters"] if item["name"] == "action")
    assert parameter["schema"]["default"] == "visible"


@pytest.mark.parametrize("action", ["edit", "delete", "publish", "use_kb", "unknown"])
async def test_unsupported_tool_query_stays_rejected(tool_http, action):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=tool_http.app), base_url="http://asgi", trust_env=False
    ) as client:
        response = await client.get("/api/v1/tool", params={"action": action})
    assert response.status_code == 422
    tool_http.listing.assert_not_awaited()
    assert tool_http.identities == []


@pytest.mark.parametrize("error", [PersonalTokenDataScopeError, PermissionInvalidResourceError])
async def test_tool_scope_and_resource_errors_never_become_successful_empty_lists(tool_http, error):
    tool_http.listing.side_effect = error()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=tool_http.app), base_url="http://asgi", trust_env=False
    ) as client:
        with pytest.raises(error):
            await client.get("/api/v1/tool", params={"action": "use"})
    assert tool_http.identities[0] is tool_http.user
