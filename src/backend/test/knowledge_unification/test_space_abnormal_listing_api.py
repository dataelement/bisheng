"""T727: original static list routes parse and forward the optional bool."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.responses import JSONResponse

from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import management_tenant_scope
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.api.endpoints import knowledge_space as api
from test.knowledge_unification import test_space_abnormal_listing_service as fixtures

concrete_tenant, store, listing = fixtures.concrete_tenant, fixtures.store, fixtures.listing


def app_for(service):
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[get_knowledge_space_service] = lambda: service

    @app.exception_handler(BaseErrorCode)
    async def business_error(request, error):
        return JSONResponse(error.return_resp_instance().model_dump(mode="json"))

    return app


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("flag", [None, False, True])
async def test_static_route_forwards_bool_and_original_page_contract(admin, flag):
    payload = (
        {"data": [], "total": 0} if admin else {"data": [], "page_size": 17, "has_more": False, "next_cursor": None}
    )
    service = SimpleNamespace(
        list_visible_spaces=AsyncMock(return_value=payload), list_admin_spaces=AsyncMock(return_value=payload)
    )
    path = "/api/v1/knowledge/space/admin/list" if admin else "/api/v1/knowledge/space/list"
    params = {"keyword": "matched", "page_size": 17, **({"page": 3} if admin else {"cursor": "original-cursor"})}
    if flag is not None:
        params["has_abnormal"] = str(flag).lower()
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="http://test") as client:
        response = await client.get(path, params=params)
    assert response.status_code == 200
    assert response.json()["status_code"] == 200 and response.json()["data"] == payload
    expected = {"keyword": "matched", "page_size": 17, "has_abnormal": flag}
    expected.update({"page": 3} if admin else {"cursor": "original-cursor"})
    (service.list_admin_spaces if admin else service.list_visible_spaces).assert_awaited_once_with(**expected)
    (service.list_visible_spaces if admin else service.list_admin_spaces).assert_not_awaited()


@pytest.mark.parametrize("path", ["list", "admin/list"])
@pytest.mark.parametrize("params", [{"has_abnormal": "not-a-bool"}, {"page_size": 201}])
async def test_invalid_filter_or_page_rejected_before_service(path, params):
    service = SimpleNamespace(list_visible_spaces=AsyncMock(), list_admin_spaces=AsyncMock())
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="http://test") as client:
        response = await client.get("/api/v1/knowledge/space/" + path, params=params)
    assert response.status_code == 422
    service.list_visible_spaces.assert_not_awaited()
    service.list_admin_spaces.assert_not_awaited()


async def test_native_service_keeps_ordinary_visibility_and_admin_denial(listing):
    await listing.store.seed(fixtures.space(1), fixtures.space(2), fixtures.file(11, 1), fixtures.file(12, 2))
    listing.allowed.add(1)
    async with AsyncClient(transport=ASGITransport(app=app_for(listing.service)), base_url="http://test") as client:
        response = await client.get("/api/v1/knowledge/space/list", params={"has_abnormal": "true"})
        assert response.status_code == 200
        result = response.json()
        assert result["status_code"] == 200
        assert [(row["id"], row["has_abnormal_files"]) for row in result["data"]["data"]] == [(1, True)]
        listing.store.facts.selects.clear()
        with management_tenant_scope(101):
            denied = await client.get("/api/v1/knowledge/space/admin/list", params={"has_abnormal": "true"})
        assert denied.status_code == 200 and denied.json()["status_code"] == PermissionDeniedError.Code
        assert listing.store.facts.selects == []
