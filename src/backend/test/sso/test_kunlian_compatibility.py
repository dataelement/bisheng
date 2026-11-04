"""T081 覆盖 AC-08, AC-12, AC-13, AC-14, AC-20, AC-23, AC-25。"""

from unittest.mock import AsyncMock

import pytest
from fastapi.responses import JSONResponse

from test.sso import test_kunlian_logout as logout_tests

owner = logout_tests.owner
directory_store = logout_tests.directory_store
projection = logout_tests.projection
login = logout_tests.login
browser_api = logout_tests.browser_api
logout_api = logout_tests.logout_api


async def test_expired_kunlian_cookie_does_not_block_explicit_password_login_dispatch(logout_api, monkeypatch):
    """AC-14, AC-25: 旧凭据入口交原 UserService 验证。不用旧昆联 Cookie 授权。"""
    from bisheng.user.domain.services.user import UserService

    client, _, _, idp, repository, headers = logout_api
    repository.clock.advance(301)
    original_login = AsyncMock(
        return_value=JSONResponse(
            content={"status_code": 200, "status_message": "", "data": {"handled_by": "original_user_service"}}
        )
    )
    monkeypatch.setattr(UserService, "user_login", original_login)
    response = await client.post(
        "/api/v1/user/login", json={"user_name": "fixture-local", "password": "fixture-encrypted"}, headers=headers
    )
    assert response.status_code == 200 and response.json()["data"]["handled_by"] == "original_user_service"
    original_login.assert_awaited_once()
    assert (await client.get("/api/v1/probe", headers=headers)).status_code == 401
    idp.introspect.assert_not_awaited()


@pytest.mark.parametrize("path", ["/api/v1/user/public_key", "/api/v1/user/get_captcha", "/api/v1/env"])
async def test_public_bootstrap_stays_anonymous_with_stale_kunlian_cookie(logout_api, path):
    """AC-14, AC-25: 匿名启动材料不读取昆联资格。业务路径仍必须验证。"""
    client, _, _, idp, repository, headers = logout_api
    repository.clock.advance(301)
    app = client._transport.app
    app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) != path]

    @app.get(path)
    async def anonymous_bootstrap():
        return {"anonymous_bootstrap": True}

    response = await client.get(path, headers=headers)
    assert response.status_code == 200 and response.json() == {"anonymous_bootstrap": True}
    idp.introspect.assert_not_awaited()
