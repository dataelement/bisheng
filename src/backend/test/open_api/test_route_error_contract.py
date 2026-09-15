"""Exercise real v2 routes, middleware, and the assistant error adapter."""

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketDisconnect

from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.common.errcode.open_api import PersonalTokenDataScopeError
from bisheng.common.errcode.permission import PermissionDeniedError, PermissionServiceUnavailableError
from bisheng.main import app
from test.open_api.test_dependencies import service_account_principal

HTTP_ROUTES = [
    (method, re.sub(r"\{[^}]+\}", "1", route.path))
    for route in app.routes
    if isinstance(route, APIRoute) and route.path.startswith("/api/v2/")
    for method in sorted(route.methods)
]


@pytest.mark.parametrize(
    "path",
    [
        "/api/v2/assistant/chat/00000000-0000-0000-0000-000000000001",
        "/api/v2/workflow/chat/00000000-0000-0000-0000-000000000001",
    ],
)
def test_websocket_denial_happens_before_accept(path):
    client = TestClient(app)
    try:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(path):
                pytest.fail("Missing credentials must not establish a WebSocket")
        assert (caught.value.code, caught.value.reason) == (1008, "26001")
    finally:
        client.close()


@pytest.mark.parametrize("method,path", HTTP_ROUTES)
@pytest.mark.parametrize("authorization", [None, "Bearer login.jwt.token"])
async def test_every_registered_v2_http_route_rejects_missing_or_malformed_key(method, path, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, headers=headers)
    assert (response.status_code, response.json()["status_code"]) == (401, 26001)


async def test_login_cookie_cannot_override_api_credential_errors(monkeypatch):
    monkeypatch.setattr(
        "bisheng.utils.http_middleware._decode_jwt_subject",
        lambda _token: {"user_id": 7, "tenant_id": 0, "token_version": 1},
    )
    validate_login_version = AsyncMock(return_value=False)
    monkeypatch.setattr("bisheng.utils.http_middleware._validate_token_version", validate_login_version)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"access_token_cookie": "stale-login"},
    ) as client:
        response = await client.get("/api/v2/auth/whoami")
    assert (response.status_code, response.json()["status_code"]) == (401, 26001)
    validate_login_version.assert_not_awaited()


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "error,http_status",
    [
        (UnAuthorizedError(), 403),
        (PermissionDeniedError(), 403),
        (SpacePermissionDeniedError(), 403),
        (PersonalTokenDataScopeError(), 403),
        (PermissionServiceUnavailableError(), 503),
        (NotFoundError(), 404),
    ],
)
async def test_assistant_keeps_authorization_error_before_stream_start(monkeypatch, error, http_status, stream):
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=service_account_principal(scopes=frozenset({"assistant:invoke"}))),
    )
    monkeypatch.setattr(
        "bisheng.open_endpoints.api.endpoints.assistant.get_open_api_operator", lambda: SimpleNamespace(user_id=12)
    )
    complete = AsyncMock(side_effect=error)
    monkeypatch.setattr("bisheng.open_endpoints.api.endpoints.assistant.PublishedAssistantService.complete", complete)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v2/assistant/chat/completions",
            json={"model": "00000000-0000-0000-0000-000000000001", "messages": [], "stream": stream},
        )
    assert response.status_code == http_status
    assert response.json()["status_code"] == error.code
    complete.assert_awaited_once()


async def test_child_tenant_key_is_not_mistaken_for_missing_account(open_api_db, fake_redis, monkeypatch):
    from bisheng.core.context.tenant import current_tenant_id
    from bisheng.open_api.domain.models.service_account import ServiceAccount
    from bisheng.open_api.domain.schemas.credential import KeyIssueRequest
    from bisheng.open_api.domain.services.credential_service import CredentialService

    async with open_api_db() as session:
        account = ServiceAccount(tenant_id=9, name="child-account", resource_owner_user_id=12)
        session.add(account)
        await session.commit()
        await session.refresh(account)
    issued = await CredentialService.issue(
        tenant_id=9,
        subject_kind="service_account",
        subject_id=account.id,
        request=KeyIssueRequest(name="child-key"),
        created_by=12,
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.credential_service.CredentialService.touch_last_used", AsyncMock()
    )
    # CustomMiddleware seeds tenant 1. Authentication must load the account in
    # the credential's tenant before replacing that initial tenant context.
    from bisheng.open_api.domain.services.credential_validator import validate_bearer

    token = current_tenant_id.set(1)
    try:
        principal = await validate_bearer(f"Bearer {issued.plaintext}")
    finally:
        current_tenant_id.reset(token)
    assert (principal.actor_id, principal.tenant_id) == (account.id, 9)
