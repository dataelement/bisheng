from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.api_rate_limit.api.endpoints.api_rate_limit import router
from bisheng.api_rate_limit.domain.schemas import ApiRateLimitConfig
from bisheng.api_rate_limit.domain.services import ApiRateLimitService
from bisheng.common.dependencies.user_deps import UserPayload


def _build_client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=1)
    return TestClient(app)


def test_get_config_returns_unified_envelope(monkeypatch):
    config = ApiRateLimitConfig.model_validate({"revision": 2, "global": {"limits": {"minute": 10}, "message": "busy"}})
    monkeypatch.setattr(ApiRateLimitService, "get_config", AsyncMock(return_value=config))

    response = _build_client().get("/admin/api-rate-limit/config")

    assert response.status_code == 200
    assert response.json()["status_code"] == 200
    assert response.json()["data"]["revision"] == 2


def test_put_config_passes_expected_revision(monkeypatch):
    saved = ApiRateLimitConfig.model_validate({"revision": 3})
    update = AsyncMock(return_value=saved)
    monkeypatch.setattr(ApiRateLimitService, "update_config", update)

    response = _build_client().put(
        "/admin/api-rate-limit/config",
        json={"expected_revision": 2, "global": {"limits": {"second": 1}}, "routes": []},
    )

    assert response.status_code == 200
    assert response.json()["data"]["revision"] == 3
    assert update.await_args.args[1].expected_revision == 2


def test_get_route_catalog_passes_validated_query_and_returns_page(monkeypatch):
    catalog = {
        "items": [
            {
                "method": "GET",
                "path": "/api/v1/knowledge/{knowledge_id}",
                "tags": ["Knowledge"],
                "primary_tag": "Knowledge",
                "name": "get_knowledge",
                "summary": "查询知识库",
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20,
        "total_pages": 1,
        "categories": ["Knowledge"],
    }
    get_route_catalog = AsyncMock(return_value=catalog)
    monkeypatch.setattr(ApiRateLimitService, "get_route_catalog", get_route_catalog)

    response = _build_client().get(
        "/admin/api-rate-limit/routes",
        params={"keyword": "knowledge", "method": "GET", "tag": "Knowledge", "page_size": 20},
    )

    assert response.status_code == 200
    assert response.json()["data"] == catalog
    assert get_route_catalog.await_args.kwargs == {
        "keyword": "knowledge",
        "method": "GET",
        "tag": "Knowledge",
        "page": 1,
        "page_size": 20,
    }


def test_get_route_catalog_rejects_invalid_page_size():
    response = _build_client().get(
        "/admin/api-rate-limit/routes",
        params={"page_size": 101},
    )

    assert response.status_code == 422
