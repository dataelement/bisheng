"""Desktop model authentication remains independent of browser session cookies."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.api.endpoints import models
from bisheng.dsh.domain.services.access import DshPrincipal
from bisheng.utils import http_middleware


@pytest.mark.parametrize("protocol", ["responses", "chat/completions"])
async def test_stale_browser_cookie_cannot_preempt_desktop_bearer(monkeypatch, protocol):
    principal = DshPrincipal(tenant_id="2", user_id="3", session_id="desktop-session")
    runtime = SimpleNamespace(access=SimpleNamespace(authenticate=AsyncMock(return_value=principal)))
    model_runtime = SimpleNamespace(complete=AsyncMock(return_value={"id": "model-result"}))
    monkeypatch.setattr(models, "get_model_runtime", AsyncMock(return_value=model_runtime))
    monkeypatch.setattr(
        http_middleware,
        "_decode_jwt_subject",
        lambda token: {"user_id": 999, "tenant_id": 1, "token_version": 0},
    )
    browser_validation = AsyncMock(return_value=False)
    monkeypatch.setattr(http_middleware, "_validate_token_version", browser_validation)
    app = FastAPI()
    app.include_router(models.router, prefix="/api/v1")
    app.add_middleware(http_middleware.CustomMiddleware)
    app.dependency_overrides[get_runtime] = lambda: runtime
    body = {
        "model": "bisheng:42",
        "input" if protocol == "responses" else "messages": [{"role": "user", "content": "hi"}],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
        response = await client.post(
            "/api/v1/dsh/" + protocol,
            headers={"Authorization": "Bearer desktop", "Cookie": "access_token_cookie=stale-browser"},
            json=body,
        )
        cookie_only = await client.post(
            "/api/v1/dsh/" + protocol,
            headers={"Cookie": "access_token_cookie=stale-browser"},
            json=body,
        )
    assert response.status_code == 200 and response.json() == {"id": "model-result"}
    assert response.headers["x-request-id"] == model_runtime.complete.await_args.kwargs["request_id"]
    assert cookie_only.status_code == 401 and cookie_only.json()["error"]["code"] == "invalid_access_token"
    runtime.access.authenticate.assert_awaited_once_with("Bearer desktop")
    model_runtime.complete.assert_awaited_once()
    browser_validation.assert_not_awaited()


def test_responses_credential_ownership_is_an_exact_method_and_path():
    assert http_middleware.owns_dsh_credential("POST", "/api/v1/dsh/responses")
    assert not http_middleware.owns_dsh_credential("GET", "/api/v1/dsh/responses")
    assert not http_middleware.owns_dsh_credential("POST", "/api/v1/dsh/responses/other")
