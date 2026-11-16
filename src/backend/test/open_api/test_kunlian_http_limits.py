"""HTTP admission contracts without Redis or business infrastructure."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.open_api import OpenApiKunlianRateLimitedError
from bisheng.open_api.application.kunlian_http import (
    KunlianApiRoute,
    get_kunlian_request_user,
    kunlian_capability,
)


@pytest.fixture
def admission_app():
    app = FastAPI()
    access = SimpleNamespace(credential=SimpleNamespace(credential_id=3), user=SimpleNamespace(user_id=17))
    business = AsyncMock(return_value={"ok": True})

    class Access:
        @asynccontextmanager
        async def use_user(self, authorization, user_account, *, capability):
            assert (user_account, capability) == ("account-a", "write")
            yield access

    app.state.kunlian_access_service = Access()
    app.state.kunlian_audit_service = SimpleNamespace(begin=AsyncMock(return_value="audit"), finish=AsyncMock())
    router = APIRouter(route_class=KunlianApiRoute)

    @router.post("/write")
    @kunlian_capability("write")
    async def write(access=Depends(get_kunlian_request_user)):
        return await business()

    app.include_router(router)
    return app, access, business


async def send(app):
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        return await client.post("/write", params={"user_account": "account-a"})


async def test_rate_limited_request_never_enters_business(admission_app, monkeypatch):
    from bisheng.common.services.config_service import settings

    def unexpected_config_read(self):
        pytest.fail("injected limiter must not read server configuration")

    monkeypatch.setattr(type(settings), "get_workflow_conf", unexpected_config_read)
    app, access, business = admission_app
    limiter = AsyncMock(side_effect=OpenApiKunlianRateLimitedError())
    app.state.kunlian_request_limiter = limiter

    response = await send(app)

    assert response.status_code == 429
    assert response.json()["status_code"] == 26074
    assert response.headers["Retry-After"] == "60"
    assert response.headers["Cache-Control"] == "no-store"
    limiter.assert_awaited_once_with(access)
    business.assert_not_awaited()


async def test_unknown_limiter_failure_propagates_without_business(admission_app):
    app, _, business = admission_app
    app.state.kunlian_request_limiter = AsyncMock(side_effect=RuntimeError("unexpected limiter failure"))

    with pytest.raises(RuntimeError, match="unexpected limiter failure"):
        await send(app)

    business.assert_not_awaited()


@pytest.mark.parametrize("limit,window", [(120, 60), (2, 17)])
async def test_default_limiter_uses_server_policy(admission_app, monkeypatch, limit, window):
    from bisheng.common.services.config_service import settings
    from bisheng.open_api.application import kunlian_limits

    monkeypatch.setattr(
        type(settings),
        "get_workflow_conf",
        lambda self: SimpleNamespace(kunlian_api=SimpleNamespace(request_limit=limit, request_window_seconds=window)),
    )
    app, _, business = admission_app
    calls = []

    async def evaluate(script, numkeys, key, window):
        calls.append((numkeys, key, window))
        return len(calls)

    redis_factory = AsyncMock(return_value=SimpleNamespace(eval=evaluate))
    monkeypatch.setattr(kunlian_limits, "get_redis_client", redis_factory)
    for _ in range(limit):
        assert (await send(app)).status_code == 200
    response = await send(app)

    assert response.status_code == 429
    assert response.json()["status_code"] == 26074
    assert response.headers["Retry-After"] == str(window)
    assert business.await_count == limit
    assert len(calls) == limit + 1
    assert set(calls) == {(1, "kunlian:request-rate:{3}", window)}


async def test_unknown_limiter_failure_propagates(admission_app):
    app, _, business = admission_app
    app.state.kunlian_request_limiter = AsyncMock(side_effect=RuntimeError("unexpected limiter bug"))

    with pytest.raises(RuntimeError, match="unexpected limiter bug"):
        await send(app)

    business.assert_not_awaited()
