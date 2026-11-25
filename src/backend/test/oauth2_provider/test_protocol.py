"""Public OAuth wire errors against the production platform exception handlers."""

from types import SimpleNamespace

import pytest
import test_oauth2_provider as provider_tests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_oauth2_provider import _issue_security_tokens

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.oauth2_provider.api.endpoints.clients import admin_router, require_super_admin
from bisheng.oauth2_provider.api.endpoints.oidc import consent_router, public_router
from bisheng.oauth2_provider.domain.models.client import BUILTIN_DSH_CLIENT_ID
from bisheng.oauth2_provider.runtime import get_oauth2_runtime

oauth2_env = provider_tests.oauth2_env


@pytest.fixture
def protocol_http_client(oauth2_env):
    from bisheng.main import _EXCEPTION_HANDLERS

    runtime, _ = oauth2_env
    # Production ordinarily converts BaseErrorCode to an HTTP 200 envelope.
    app = FastAPI(exception_handlers=_EXCEPTION_HANDLERS)
    app.include_router(public_router, prefix="/api/v1")
    app.include_router(consent_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    user = SimpleNamespace(user_id=42, tenant_id=7, is_global_super=True)
    app.dependency_overrides[get_oauth2_runtime] = lambda: runtime
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    app.dependency_overrides[require_super_admin] = lambda: user
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    "method,path,body,status,error,challenge",
    [
        ("post", "/token", {"grant_type": "password"}, 400, "unsupported_grant_type", None),
        ("post", "/token", {"grant_type": "authorization_code"}, 400, "invalid_request", None),
        (
            "post",
            "/token",
            {
                "grant_type": "authorization_code",
                "client_id": "dsh-desktop",
                "redirect_uri": "http://127.0.0.1/dsh/callback",
                "code": "used-or-missing",
            },
            400,
            "invalid_grant",
            None,
        ),
        (
            "post",
            "/token",
            {
                "grant_type": "authorization_code",
                "client_id": "unknown",
                "redirect_uri": "https://example/cb",
                "code": "missing",
            },
            401,
            "invalid_client",
            "Basic",
        ),
        ("get", "/userinfo", None, 401, "invalid_token", "Bearer"),
        (
            "post",
            "/revoke",
            {"client_id": "security-client", "client_secret": "wrong", "token": "unknown"},
            401,
            "invalid_client",
            "Basic",
        ),
        ("get", "/authorize", None, 400, "invalid_request", None),
    ],
)
async def test_protocol_errors_override_real_global_platform_handler(
    oauth2_env, protocol_http_client, method, path, body, status, error, challenge
):
    runtime, _ = oauth2_env
    await _issue_security_tokens(runtime, client_type="confidential")
    response = getattr(protocol_http_client, method)(
        f"/api/v1/oauth2{path}", **({"data": body} if body is not None else {})
    )
    assert response.status_code == status, response.text
    assert response.json()["error"] == error
    assert "status_code" not in response.json()
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    if challenge:
        assert response.headers["www-authenticate"].startswith(challenge)
    else:
        assert "www-authenticate" not in response.headers


def test_protocol_json_errors_and_platform_envelopes_stay_separate(protocol_http_client):
    malformed = protocol_http_client.post(
        "/api/v1/oauth2/token", content="{", headers={"content-type": "application/json"}
    )
    assert malformed.status_code == 400
    assert malformed.json()["error"] == "invalid_request"
    consent = protocol_http_client.get("/api/v1/oauth2/consent/missing")
    assert consent.status_code == 200
    assert consent.json()["status_code"] == 28108
    assert protocol_http_client.get("/api/v1/oauth2/clients").status_code == 200
    admin = protocol_http_client.delete(f"/api/v1/oauth2/clients/{BUILTIN_DSH_CLIENT_ID}")
    assert admin.status_code == 200
    assert admin.json()["status_code"] == 28111


async def test_protocol_success_tokens_userinfo_and_revoke_are_not_cacheable(oauth2_env, protocol_http_client):
    runtime, _ = oauth2_env
    tokens, secret = await _issue_security_tokens(runtime, client_type="confidential")
    refreshed = protocol_http_client.post(
        "/api/v1/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
            "client_id": "security-client",
            "client_secret": secret,
        },
    )
    assert refreshed.status_code == 200 and "access_token" in refreshed.json()
    info = protocol_http_client.get(
        "/api/v1/oauth2/userinfo", headers={"authorization": f"Bearer {refreshed.json()['access_token']}"}
    )
    assert info.status_code == 200 and info.json()["sub"] == "42"
    revoked = protocol_http_client.post(
        "/api/v1/oauth2/revoke",
        data={"token": refreshed.json()["refresh_token"], "client_id": "security-client", "client_secret": secret},
    )
    assert revoked.status_code == 200
    for response in (refreshed, info, revoked):
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["pragma"] == "no-cache"
