"""正式用户依赖的 HTTP 边界, 不伪造业务鉴权。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def account_app():
    from bisheng.open_api.api.kunlian_dependencies import (
        KunlianApiRoute,
        get_kunlian_request_user,
        kunlian_capability,
    )

    app = FastAPI()
    router = APIRouter(route_class=KunlianApiRoute)
    admissions = []

    class Access:
        @asynccontextmanager
        async def use_user(self, authorization, user_account, *, capability):
            assert (authorization, user_account, capability) == ("Bearer synthetic", "account-a", "read")
            admissions.append(user_account)
            yield SimpleNamespace(user=SimpleNamespace(user_id=17))

    app.state.kunlian_access_service = Access()
    app.state.kunlian_request_limiter = AsyncMock(return_value=None)
    app.state.kunlian_audit_service = SimpleNamespace(
        begin=AsyncMock(return_value="test-audit"), finish=AsyncMock(return_value=True)
    )
    business = AsyncMock(return_value={"user": 17})

    @router.get("/workflows")
    @kunlian_capability("read")
    async def endpoint(access=Depends(get_kunlian_request_user)):
        return await business()

    app.include_router(router)
    return app, admissions, business


async def test_public_user_account_requires_no_legacy_identity(account_app):
    app, admissions, business = account_app
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get(
            "/workflows", params={"user_account": "account-a"}, headers={"Authorization": "Bearer synthetic"}
        )
    assert response.status_code == 200
    assert response.json()["user"] == 17
    assert admissions == ["account-a"]
    business.assert_awaited_once()


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"external_tenant_id": "tenant-a", "external_user_id": "subject-a"},
        {"user_account": "account-a", "external_tenant_id": "tenant-a"},
        {"user_account": "account-a", "external_user_id": "subject-a"},
        {"user_account": "account-a", "external_tenant_id": "tenant-a", "external_user_id": "subject-a"},
        [("user_account", "account-a"), ("user_account", "other")],
        {"user_account": ""},
        {"user_account": "a" * 129},
    ],
    ids=[
        "missing-account",
        "legacy-only",
        "mixed-tenant",
        "mixed-user",
        "mixed-both",
        "duplicate-account",
        "empty-account",
        "oversize-account",
    ],
)
async def test_legacy_or_ambiguous_query_rejected_before_admission(account_app, params):
    app, admissions, business = account_app
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/workflows", params=params, headers={"Authorization": "Bearer synthetic"})
    assert response.status_code == 422
    assert admissions == []
    business.assert_not_awaited()
    app.state.kunlian_request_limiter.assert_not_awaited()
    app.state.kunlian_audit_service.begin.assert_not_awaited()


async def test_account_query_still_rejects_mixed_identity_headers(account_app):
    app, admissions, business = account_app
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get(
            "/workflows",
            params={"user_account": "account-a"},
            headers={"Authorization": "Bearer synthetic", "X-On-Behalf-Of": "1"},
        )
    assert response.status_code == 422
    assert admissions == []
    business.assert_not_awaited()


def test_public_openapi_declares_only_account_identity(account_app):
    app, _, _ = account_app
    parameters = app.openapi()["paths"]["/workflows"]["get"]["parameters"]
    query = {parameter["name"]: parameter for parameter in parameters if parameter["in"] == "query"}
    assert set(query) == {"user_account"}
    assert query["user_account"]["required"] is True
