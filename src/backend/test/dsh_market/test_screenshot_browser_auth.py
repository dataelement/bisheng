"""Browser and desktop credentials on the exact screenshot route."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import Depends, FastAPI

from bisheng.core.context import tenant as context
from bisheng.dsh.domain.services import web_session
from bisheng.dsh.domain.services.access import DshAccessService
from bisheng.dsh_market.api.auth import MarketActor, market_actor
from bisheng.user.domain.services.auth import AuthJwt, LoginUser
from bisheng.utils.http_middleware import CustomMiddleware, owns_dsh_credential
from test.dsh.test_access import Identities, Keys
from test.dsh.test_access import token as desktop_token
from test.dsh_market.test_desktop_auth import Sessions

PATH = "/api/v1/dsh/market/workbenches/" + "a" * 32 + "/versions/" + "b" * 32 + "/screenshots/" + "c" * 64


@pytest.fixture
def browser_app(monkeypatch):
    import bisheng.core.cache.redis_manager as redis_manager
    import bisheng.dsh.access_runtime as runtime
    import bisheng.user.domain.services.jwt_secret as jwt_secret
    import bisheng.utils.http_middleware as middleware
    from bisheng.common.services.config_service import settings
    from bisheng.user.domain.models.user import UserDao

    monkeypatch.setattr(jwt_secret, "resolve_jwt_secret", lambda: "fixture-signing-key-long-enough-32")
    monkeypatch.setattr(UserDao, "aget_token_version", AsyncMock(return_value=3))
    monkeypatch.setattr(UserDao, "aget_user", AsyncMock(return_value=SimpleNamespace(delete=0)))
    monkeypatch.setattr(middleware, "_check_is_global_super", AsyncMock(return_value=False))
    monkeypatch.setattr(
        LoginUser,
        "init_login_user",
        AsyncMock(return_value=SimpleNamespace(tenant_id=2, user_id=1001, is_global_super=False)),
    )
    monkeypatch.setattr(
        type(settings), "aget_system_login_method", AsyncMock(return_value=SimpleNamespace(allow_multi_login=False))
    )
    redis = SimpleNamespace(aget=AsyncMock(return_value=None))
    monkeypatch.setattr(redis_manager, "get_redis_client", AsyncMock(return_value=redis))
    sessions = Sessions()
    access = DshAccessService("test-issuer", Keys(), Identities(), sessions)
    monkeypatch.setattr(runtime, "get_runtime", AsyncMock(return_value=SimpleNamespace(access=access)))
    store = SimpleNamespace(get=AsyncMock(return_value=("Bearer " + desktop_token()).encode()))
    monkeypatch.setattr(web_session, "session_store", AsyncMock(return_value=store))
    app = FastAPI()
    app.add_middleware(CustomMiddleware)

    @app.middleware("http")
    async def inherited_scope(request, call_next):
        tokens = [
            context._bypass_tenant_filter.set(True),
            context.set_admin_scope_tenant_id(99),
            context._strict_tenant_filter.set(True),
        ]
        try:
            return await call_next(request)
        finally:
            for scope_token in reversed(tokens):
                scope_token.var.reset(scope_token)

    @app.get(PATH)
    async def screenshot(actor: MarketActor = Depends(market_actor)):
        return {
            "tenant": actor.tenant_id,
            "user": actor.user_id,
            "desktop": actor.desktop,
            "visible": sorted(context.get_visible_tenant_ids()),
            "bypass": context.is_tenant_filter_bypassed(),
            "admin_scope": context.get_admin_scope_tenant_id(),
            "strict": context._strict_tenant_filter.get(),
        }

    return app, redis, store, sessions


def web_token(**extra):
    return AuthJwt().create_access_token({"user_id": 1001, "tenant_id": 2, "token_version": 3, **extra})


@pytest.mark.parametrize("transport", ["cookie", "bearer"])
@pytest.mark.parametrize("case", ["valid", "displaced", "disabled", "version", "revoked_web"])
async def test_browser_lifecycle(browser_app, transport, case):
    from bisheng.common.errcode.user import UserLoginOfflineError
    from bisheng.user.domain.models.user import UserDao

    app, redis, store, _ = browser_app
    token = web_token(**({"dsh_web_session": "x" * 43} if case == "revoked_web" else {}))
    if case == "displaced":
        redis.aget.return_value = "another-session"
    if case == "disabled":
        UserDao.aget_user.return_value = SimpleNamespace(delete=1)
    if case == "version":
        UserDao.aget_token_version.return_value = 4
    if case == "revoked_web":
        store.get.return_value = None
    headers = (
        {"Cookie": "access_token_cookie=" + token} if transport == "cookie" else {"Authorization": "Bearer " + token}
    )
    assert owns_dsh_credential("GET", PATH)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        response = await client.get(PATH, headers=headers)
    if case == "valid":
        assert response.json() == {
            "tenant": 2,
            "user": 1001,
            "desktop": False,
            "visible": [2],
            "bypass": False,
            "admin_scope": None,
            "strict": False,
        }
    else:
        assert response.status_code == 401
        assert (
            response.json()["status_code"]
            == {"displaced": UserLoginOfflineError.Code, "disabled": 19104, "version": 19103, "revoked_web": 19103}[
                case
            ]
        )
        assert response.json()["data"] is None


async def test_desktop_ignores_stale_cookie(browser_app):
    app, redis, _, _ = browser_app
    redis.aget.return_value = "another-session"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        response = await client.get(
            PATH, headers={"Authorization": "Bearer " + desktop_token(), "Cookie": "access_token_cookie=stale"}
        )
    assert response.status_code == 200
    assert response.json() == {
        "tenant": 2,
        "user": 1001,
        "desktop": True,
        "visible": [2],
        "bypass": False,
        "admin_scope": None,
        "strict": False,
    }
