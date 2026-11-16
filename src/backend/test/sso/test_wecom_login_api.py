"""F120 — WeCom SSO endpoints (redirect + cookie contract)."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from bisheng.common.errcode.sso_sync import (
    WeComSsoNotConfiguredError,
    WeComSsoStateInvalidError,
)
from bisheng.sso_sync.api.endpoints import wecom_login as mod
from bisheng.sso_sync.api.endpoints.wecom_login import router
from bisheng.sso_sync.domain.services.wecom_login_service import WeComLoginService


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        mod,
        "settings",
        SimpleNamespace(
            cookie_conf=SimpleNamespace(
                max_age=None,
                jwt_token_expire_time=86400,
                path="/",
                domain=None,
                secure=False,
                samesite="lax",
            )
        ),
    )
    return TestClient(_app(), follow_redirects=False)


@pytest.fixture
def service(monkeypatch):
    """Replace the orchestration calls; the tests only assert the HTTP contract."""

    async def _availability(user_agent):
        return {"enabled": True, "mode": "qr", "login_path": "/api/v1/user/wecom/authorize"}

    monkeypatch.setattr(WeComLoginService, "availability", _availability)
    return monkeypatch


def test_availability_returns_envelope(client, service):
    response = client.get("/user/wecom/availability")
    assert response.status_code == 200
    body = response.json()
    assert body["status_code"] == 200
    assert body["data"]["enabled"] is True


def test_authorize_redirects_to_wecom(client, service):
    async def _authorize(**kwargs):
        assert kwargs["public_origin"] == "http://testserver"
        assert kwargs["callback_url"] == "http://testserver/api/v1/user/wecom/callback"
        return "https://login.work.weixin.qq.com/wwlogin/sso/login?appid=ww123"

    service.setattr(WeComLoginService, "authorize", _authorize)

    response = client.get("/user/wecom/authorize", params={"return_to": "http://testserver/build"})

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://login.work.weixin.qq.com/")


def test_authorize_failure_returns_to_login_with_error_code(client, service):
    async def _authorize(**kwargs):
        raise WeComSsoNotConfiguredError()

    service.setattr(WeComLoginService, "authorize", _authorize)

    response = client.get("/user/wecom/authorize")

    assert response.status_code == 302
    assert response.headers["location"] == "http://testserver/?wecom_error=19330"


def test_callback_sets_cookie_and_redirects_without_token_in_url(client, service):
    async def _callback(**kwargs):
        return "http://testserver/build/apps", "jwt-token"

    service.setattr(WeComLoginService, "callback", _callback)

    response = client.get("/user/wecom/callback", params={"code": "c", "state": "s"})

    assert response.status_code == 302
    location = response.headers["location"]
    assert location == "http://testserver/build/apps"
    # INV-46: the session token must never ride in the URL.
    assert "jwt-token" not in location
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("access_token_cookie=jwt-token")
    # The platform mirrors the cookie into localStorage.ws_token (design §3 dec. 2).
    assert "HttpOnly" not in cookie


def test_callback_failure_reports_state_error(client, service):
    async def _callback(**kwargs):
        raise WeComSsoStateInvalidError()

    service.setattr(WeComLoginService, "callback", _callback)

    response = client.get("/user/wecom/callback", params={"code": "c", "state": "bad"})

    assert response.status_code == 302
    assert response.headers["location"] == "http://testserver/?wecom_error=19332"


def test_callback_refusal_from_login_sync_still_returns_to_login(client, service):
    # Disabled account / concurrent login surface as HTTPException from
    # LoginSyncService; the browser must still land on the login page.
    async def _callback(**kwargs):
        raise HTTPException(status_code=10620, detail="Account cannot be used")

    service.setattr(WeComLoginService, "callback", _callback)

    response = client.get("/user/wecom/callback", params={"code": "c", "state": "s"})

    assert response.status_code == 302
    assert response.headers["location"] == "http://testserver/?wecom_error=10620"
