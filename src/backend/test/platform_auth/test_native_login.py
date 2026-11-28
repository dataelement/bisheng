"""Native password login stories using the real session authority and temporary SQL."""

import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from bisheng.user.domain.schemas.password_identity import PasswordLoginIdentity
from test.platform_auth.test_platform_api import app_for
from test.platform_auth.test_platform_session import runtime as _runtime
from test.platform_auth.test_platform_wiring import settings_env as _settings_env

runtime = _runtime
settings_env = _settings_env


@pytest.mark.parametrize("native_client", ["bisheng-mobile", "bisheng-desktop"])
async def test_native_password_login_rotates_without_browser_cookies(runtime, settings_env, monkeypatch, native_client):
    """Verified credentials issue a native session; rotation keeps client identity and logout revokes it."""
    from bisheng.user.domain.services.user import UserService

    service, _, _ = runtime
    person = SimpleNamespace(user_id=7, user_name="unit-native-password")
    identity = PasswordLoginIdentity(person, 9, (2,), False, 0)
    authenticate = AsyncMock(return_value=identity)
    complete = AsyncMock(return_value=({"default_entry": "/workspace"}, None))
    monkeypatch.setattr(UserService, "authenticate_password", authenticate)
    monkeypatch.setattr(UserService, "complete_password_login", complete)
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="https://platform.test") as client:
        logged_in = await client.post(
            "/api/v1/auth/login",
            json={
                "user_name": person.user_name,
                "password": secrets.token_urlsafe(32),
                "client_id": native_client,
                "client_version": "1.1.0",
                "device_label": "Unit native device",
            },
        )
        assert logged_in.status_code == 200
        first = logged_in.json()["data"]
        assert first["refresh_mode"] == "native"
        assert first["auth_source"] == "platform"
        assert first["refresh_token"] and first["access_token"]
        assert not logged_in.headers.get_list("set-cookie")
        assert logged_in.headers["cache-control"] == "no-store"
        authenticate.assert_awaited_once()
        complete.assert_awaited_once()
        assert service.decode(first["access_token"])["client_id"] == native_client
        rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
        assert rotated.status_code == 200
        second = rotated.json()["data"]
        assert second["refresh_mode"] == "native"
        assert second["session_id"] == first["session_id"]
        assert service.decode(second["access_token"])["client_id"] == native_client
        assert second["refresh_token"] != first["refresh_token"]
        assert not rotated.headers.get_list("set-cookie")
        state = await client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {second['access_token']}"})
        assert state.status_code == 200
        assert state.json()["data"]["refresh_mode"] == "native"
        assert "access_token" not in state.json()["data"]
        assert "refresh_token" not in state.json()["data"]
        logout = await client.post("/api/v1/auth/logout", json={"refresh_token": second["refresh_token"]})
        assert logout.status_code == 200
        denied = await client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
        assert denied.status_code == 401
        assert denied.json()["data"]["auth_reason"] == "session_revoked"


@pytest.mark.parametrize("cookie", ["platform_session_hint=" + "a" * 32, "platform_access_" + "a" * 32 + "=old"])
async def test_desktop_login_rejects_browser_credentials_before_authentication(
    runtime, settings_env, monkeypatch, cookie
):
    from bisheng.user.application import platform_auth

    service, _, _ = runtime
    authenticate = AsyncMock()
    monkeypatch.setattr(platform_auth, "validate_password_identity", authenticate)
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="https://platform.test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"user_name": "unit-native", "password": secrets.token_urlsafe(32), "client_id": "bisheng-desktop"},
            headers={"Cookie": cookie},
        )
    assert response.status_code == 403
    assert response.json()["data"]["auth_reason"] == "csrf_rejected"
    authenticate.assert_not_awaited()


async def test_unknown_client_cannot_issue_a_first_party_session(runtime, settings_env, monkeypatch):
    from bisheng.common.errcode.platform_auth import PlatformAuthError
    from bisheng.user.application import platform_auth

    service, _, _ = runtime
    authenticate = AsyncMock()
    monkeypatch.setattr(platform_auth, "validate_password_identity", authenticate)
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="https://platform.test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"user_name": "unit-native", "password": secrets.token_urlsafe(32), "client_id": "unknown-native"},
        )
    assert response.status_code == 400
    assert response.json()["data"]["auth_reason"] == "invalid_auth_request"
    authenticate.assert_not_awaited()
    with pytest.raises(PlatformAuthError, match="invalid_auth_request"):
        await service.issue(7, 9, "unknown-native")


async def test_desktop_bearer_enters_existing_business_api_and_logout_blocks_it(runtime, settings_env, monkeypatch):
    """The real profile route uses production admission, platform auth and UserPayload, for a non-admin."""
    from bisheng.admin.application.request_admission import install_request_admission
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.request_scope import RequestScope, inherit_scope
    from bisheng.common.services.config_service import settings
    from bisheng.user.api.endpoints.profile import router as profile_router
    from bisheng.user.domain.services.nickname_service import NicknameService

    service, _, _ = runtime
    issued = await service.issue(7, 9, "bisheng-desktop")
    # The existing endpoint constructs AuthJwt even when admission has cached the platform actor.
    monkeypatch.setattr(settings, "jwt_secret", secrets.token_urlsafe(48))
    actor = UserPayload(user_id=7, user_name="unit-native", tenant_id=9, user_role=[], is_global_super=False)
    hydrate = AsyncMock(return_value=actor)
    rename = AsyncMock(return_value=SimpleNamespace(user_id=7, user_name="updated-native", external_id=None))
    monkeypatch.setattr(UserPayload, "init_login_user", hydrate)
    monkeypatch.setattr(NicknameService, "arename_self", rename)
    app = app_for(service)
    app.router.routes[:] = [route for route in app.routes if route.path.startswith("/api/v1/")]
    inherit_scope(profile_router, RequestScope.IDENTITY)
    app.include_router(profile_router, prefix="/api/v1")
    install_request_admission(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://platform.test") as client:
        headers = {"Authorization": f"Bearer {issued['access_token']}"}
        response = await client.patch(
            "/api/v1/user/profile/nickname", json={"user_name": "updated-native"}, headers=headers
        )
        assert response.status_code == 200
        assert response.json()["data"]["user_id"] == 7
        assert response.json()["data"]["user_name"] == "updated-native"
        assert not actor.is_global_super
        assert actor._runtime_credential_reference["session_id"] == issued["session_id"]
        assert hydrate.await_args.kwargs["require_current_super"] is True
        assert rename.await_args.args[0].tenant_id == 9
        assert rename.await_args.args[0].user_id == 7
        logged_out = await client.post("/api/v1/auth/logout", headers=headers)
        assert logged_out.status_code == 200
        denied = await client.patch(
            "/api/v1/user/profile/nickname", json={"user_name": "never-written"}, headers=headers
        )
        assert denied.status_code == 401
        assert denied.json()["data"]["auth_reason"] == "session_revoked"
        rename.assert_awaited_once()
