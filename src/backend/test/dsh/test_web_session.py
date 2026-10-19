"""Desktop browser exchange preserves tenant scope and live grant revocation."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
import pytest

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError
from bisheng.dsh.domain.services import web_session
from bisheng.dsh.domain.services.access import DshPrincipal


@pytest.fixture(autouse=True)
def restore_visible_tenant_context():
    from bisheng.core.context.tenant import set_visible_tenant_ids

    token = set_visible_tenant_ids(None)
    yield
    token.var.reset(token)


def principal():
    return DshPrincipal(tenant_id="2", user_id="42", seat_id="seat", session_id="session", grant_version=1)


async def test_exchange_binds_short_cookie_and_keeps_access_token_server_side(monkeypatch):
    redis = SimpleNamespace(set=AsyncMock())
    monkeypatch.setattr(web_session, "session_store", AsyncMock(return_value=redis))
    access = "Bearer " + jwt.encode(
        {"exp": int(time.time()) + 90}, "fixture-signing-key-long-enough-32", algorithm="HS256"
    )
    runtime = SimpleNamespace(access=SimpleNamespace(authenticate=AsyncMock(return_value=principal())))
    user = SimpleNamespace(user_name="Alice", token_version=3, delete=0)
    with (
        patch("bisheng.user.domain.models.user.UserDao.aget_user", AsyncMock(return_value=user)),
        patch("bisheng.user.domain.services.auth.AuthJwt") as auth,
    ):
        auth.return_value.create_access_token.return_value = "browser-cookie"
        result = await web_session.create_web_session(runtime, access)
    assert 30 <= result["expires_in"] <= 90
    assert result["cookie"] == "browser-cookie"
    subject = auth.return_value.create_access_token.call_args.args[0]
    assert subject["tenant_id"] == 2
    assert subject["user_id"] == 42
    assert subject["token_version"] == 3
    assert len(subject["dsh_web_session"]) == 43
    assert access not in str(subject)
    assert redis.set.call_args.args[1] == access
    assert redis.set.call_args.kwargs["ex"] == result["expires_in"]


async def test_exchange_rejects_revoked_access():
    runtime = SimpleNamespace(access=SimpleNamespace(authenticate=AsyncMock(side_effect=DshInvalidAccessTokenError())))
    with pytest.raises(DshInvalidAccessTokenError):
        await web_session.create_web_session(runtime, "Bearer revoked")


@pytest.mark.parametrize("case", ["expired", "revoked", "tenant_changed", "valid"])
async def test_browser_requests_recheck_desktop_grant(monkeypatch, case):
    redis = SimpleNamespace(get=AsyncMock(return_value=None if case == "expired" else b"Bearer desktop"))
    monkeypatch.setattr(web_session, "session_store", AsyncMock(return_value=redis))
    authenticate = AsyncMock(return_value=principal())
    if case == "revoked":
        authenticate.side_effect = DshInvalidAccessTokenError()
    runtime = SimpleNamespace(access=SimpleNamespace(authenticate=authenticate))
    subject = {"dsh_web_session": "x" * 43, "user_id": 42, "tenant_id": 3 if case == "tenant_changed" else 2}
    with (
        patch("bisheng.dsh.access_runtime.get_runtime", AsyncMock(return_value=runtime)),
        patch("bisheng.dsh.access_runtime.get_settings"),
    ):
        if case == "valid":
            await web_session.validate_web_session(SimpleNamespace(), subject)
            authenticate.assert_awaited_once_with("Bearer desktop")
        else:
            with pytest.raises(DshInvalidAccessTokenError):
                await web_session.validate_web_session(SimpleNamespace(), subject)


async def test_http_middleware_rejects_revoked_desktop_cookie():
    from bisheng.utils.http_middleware import _apply_token_version_and_visible

    subject = {"user_id": 42, "tenant_id": 2, "token_version": 3, "dsh_web_session": "x" * 43}
    with patch.object(web_session, "validate_web_session", AsyncMock(side_effect=DshInvalidAccessTokenError())):
        result = await _apply_token_version_and_visible(SimpleNamespace(), "cookie", decoded_subject=subject)
    assert result.status_code == 401


async def test_websocket_login_rechecks_desktop_cookie():
    from bisheng.user.domain.services.auth import LoginUser

    subject = {"user_id": 42, "user_name": "Alice", "tenant_id": 2, "token_version": 3, "dsh_web_session": "x" * 43}
    auth = SimpleNamespace(get_subject=lambda **kwargs: subject)
    with (
        patch.object(web_session, "validate_web_session", AsyncMock(side_effect=DshInvalidAccessTokenError())),
        patch.object(LoginUser, "init_login_user", AsyncMock()) as initialize,
    ):
        with pytest.raises(DshInvalidAccessTokenError):
            await LoginUser.get_login_user_from_ws(SimpleNamespace(), auth)
    initialize.assert_not_called()


@pytest.mark.parametrize("remaining,deleted", [(29, 0), (90, 1), (90, None)])
async def test_exchange_rejects_expiring_or_inactive_identity(monkeypatch, remaining, deleted):
    redis = SimpleNamespace(set=AsyncMock())
    monkeypatch.setattr(web_session, "session_store", AsyncMock(return_value=redis))
    monkeypatch.setattr(web_session.time, "time", lambda: 1000)
    access = "Bearer " + jwt.encode({"exp": 1000 + remaining}, "fixture-signing-key-long-enough-32", algorithm="HS256")
    runtime = SimpleNamespace(access=SimpleNamespace(authenticate=AsyncMock(return_value=principal())))
    user = None if deleted is None else SimpleNamespace(user_name="Alice", token_version=3, delete=deleted)
    with patch("bisheng.user.domain.models.user.UserDao.aget_user", AsyncMock(return_value=user)):
        with pytest.raises(DshInvalidAccessTokenError):
            await web_session.create_web_session(runtime, access)
    redis.set.assert_not_awaited()


@pytest.mark.parametrize("desktop,token_valid", [(True, True), (True, False), (False, True)])
async def test_browser_and_desktop_session_policies(monkeypatch, desktop, token_valid):
    import bisheng.utils.http_middleware as middleware

    subject = {"user_id": 42, "tenant_id": 2, "token_version": 3}
    if desktop:
        subject["dsh_web_session"] = "x" * 43
    validate = AsyncMock()
    current = AsyncMock(return_value=False)
    monkeypatch.setattr(web_session, "validate_web_session", validate)
    monkeypatch.setattr(middleware, "_validate_token_version", AsyncMock(return_value=token_valid))
    monkeypatch.setattr(middleware, "_validate_current_session_token", current)
    monkeypatch.setattr(middleware, "_check_is_global_super", AsyncMock(return_value=False))
    with patch("bisheng.user.domain.models.user.UserDao.aget_user", AsyncMock(return_value=SimpleNamespace(delete=0))):
        result = await middleware._apply_token_version_and_visible(SimpleNamespace(), "cookie", decoded_subject=subject)
    if desktop and token_valid:
        assert result is None
        current.assert_not_awaited()
    else:
        assert result.status_code == 401
    assert validate.await_count == int(desktop)
    assert current.await_count == int(not desktop)


@pytest.mark.parametrize(
    "headers,status",
    [
        ([], 401),
        ([("Cookie", "access_token_cookie=ordinary-browser-cookie")], 401),
        ([("Authorization", "Bearer one"), ("Authorization", "Bearer two")], 401),
        ([("Authorization", "Bearer desktop")], 200),
    ],
)
async def test_registered_exchange_route_owns_desktop_credentials(monkeypatch, headers, status):
    import httpx
    from fastapi import FastAPI

    import bisheng.utils.http_middleware as middleware
    from bisheng.dsh.api.dependencies import get_runtime
    from bisheng.dsh.api.endpoints import web_session as endpoint
    from bisheng.dsh.api.router import router
    from bisheng.utils.http_middleware import CustomMiddleware

    exchange = AsyncMock(return_value={"cookie": "browser-cookie", "expires_in": 300})
    monkeypatch.setattr(endpoint, "create_web_session", exchange)
    decoded = []
    monkeypatch.setattr(middleware, "_decode_jwt_subject", lambda token: decoded.append(token))
    app = FastAPI()
    app.add_middleware(CustomMiddleware)
    app.include_router(router, prefix="/api/v1")
    runtime = SimpleNamespace()
    app.dependency_overrides[get_runtime] = lambda: runtime
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        response = await client.post("/api/v1/dsh/web-session", headers=headers, json={})
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert decoded == []
    if status == 200:
        assert response.json() == {"cookie": "browser-cookie", "expires_in": 300}
        exchange.assert_awaited_once_with(runtime, "Bearer desktop")
    else:
        exchange.assert_not_awaited()
