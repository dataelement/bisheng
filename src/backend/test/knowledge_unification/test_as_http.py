"""T137: assistant HTTP compatibility canonicalizes only the retired action.

The real router runs in an isolated ASGI app; authentication and the downstream
service are explicit ports, so transport tests do not contact middleware.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.permission import PermissionInvalidResourceError


@pytest.fixture
def assistant_http(monkeypatch):
    from bisheng.api.v1 import assistant as module

    identity = SimpleNamespace(user_id=15, tenant_id=101, user_role=[], is_global_super=False)
    page = {
        "data": [{"id": "visible-only", "write": False}],
        "page_size": 2,
        "has_more": True,
        "next_cursor": "next-cursor",
    }
    listing = AsyncMock(return_value=page)
    monkeypatch.setattr(module.AssistantService, "aget_assistant_envelope", listing)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/v1")
    app.dependency_overrides[module.UserPayload.get_login_user] = lambda: identity
    return SimpleNamespace(module=module, app=app, identity=identity, page=page, listing=listing)


@pytest.mark.parametrize("action", [None, "use", "visible"])
async def test_http_list_preserves_identity_filters_cursor_and_envelope(assistant_http, action):
    case = assistant_http
    params = {"name": "same", "tag_id": "8", "page_size": "2", "status": "2", "cursor": "original-cursor"}
    if action is not None:
        params["action"] = action
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=case.app), base_url="http://asgi", trust_env=False
    ) as client:
        response = await client.get("/api/v1/assistant", params=params)
    assert response.status_code == 200
    assert response.json() == {"status_code": 200, "status_message": "SUCCESS", "data": case.page}
    assert case.listing.await_args.args[0] is case.identity
    assert case.listing.await_args.kwargs == {
        "name": "same",
        "tag_id": 8,
        "page_size": 2,
        "status": 2,
        "cursor": "original-cursor",
        "action": "visible",
    }


async def test_openapi_default_is_canonical_visible(assistant_http):
    operation = assistant_http.app.openapi()["paths"]["/api/v1/assistant"]["get"]
    action = next(parameter for parameter in operation["parameters"] if parameter["name"] == "action")
    assert action["schema"]["default"] == "visible"


@pytest.mark.parametrize("action", ["edit", "use_kb", "publish"])
async def test_unsupported_list_action_remains_rejected(assistant_http, action):
    case = assistant_http
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=case.app), base_url="http://asgi", trust_env=False
    ) as client:
        response = await client.get("/api/v1/assistant", params={"action": action})
    assert response.status_code == 422
    case.listing.assert_not_awaited()


@pytest.mark.parametrize("error", [UnAuthorizedError, PermissionInvalidResourceError])
async def test_http_scope_or_resource_failure_is_not_replaced_by_an_empty_page(assistant_http, error):
    case = assistant_http
    case.listing.side_effect = error()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=case.app), base_url="http://asgi", trust_env=False
    ) as client:
        with pytest.raises(error):
            await client.get("/api/v1/assistant", params={"action": "use"})
    assert case.listing.await_args.args[0] is case.identity


@pytest.fixture
def assistant_socket(assistant_http, monkeypatch):
    case = assistant_http
    case.socket = SimpleNamespace(close=AsyncMock())
    case.gate = AsyncMock()
    case.dispatch = AsyncMock()
    monkeypatch.setattr(case.module, "require_business_action", case.gate)
    monkeypatch.setattr(case.module.chat_manager, "dispatch_client", case.dispatch)
    return case


async def test_socket_uses_visible_and_passes_the_original_identity_and_lease(assistant_socket):
    case = assistant_socket
    await case.module.chat(
        assistant_id="assistant-a",
        websocket=case.socket,
        login_user=case.identity,
        chat_id="chat-a",
        flow_lease_id="lease-a",
    )
    case.gate.assert_awaited_once_with(
        case.identity, resource_type="assistant", resource_id="assistant-a", action="visible"
    )
    assert case.dispatch.await_args.args[3] is case.identity
    assert case.dispatch.await_args.args[:3] == (case.socket, "assistant-a", "chat-a")
    assert case.dispatch.await_args.kwargs == {"flow_lease_id": "lease-a"}
    case.socket.close.assert_not_awaited()


@pytest.mark.parametrize("error", [UnAuthorizedError, PermissionInvalidResourceError])
async def test_socket_does_not_dispatch_a_denied_or_invalid_assistant(assistant_socket, error):
    case = assistant_socket
    case.gate.side_effect = error()
    await case.module.chat(assistant_id="assistant-a", websocket=case.socket, login_user=case.identity)
    case.dispatch.assert_not_awaited()
    case.socket.close.assert_awaited_once()
    if error is UnAuthorizedError:
        assert case.socket.close.await_args.kwargs["code"] == 1008
