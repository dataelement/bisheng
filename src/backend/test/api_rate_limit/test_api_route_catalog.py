from fastapi import FastAPI, WebSocket

from bisheng.api_rate_limit.domain.schemas import HttpMethod
from bisheng.api_rate_limit.domain.services.api_route_catalog_service import (
    UNCATEGORIZED_ROUTE_TAG,
    ApiRouteCatalogService,
)


def _build_routes():
    app = FastAPI()

    @app.get("/api/v1/knowledge/{knowledge_id}", tags=["Knowledge"], summary="查询知识库")
    async def get_knowledge(knowledge_id: int):
        return {"id": knowledge_id}

    @app.post("/api/v1/knowledge/{knowledge_id}", tags=["Knowledge", "Admin"])
    async def update_knowledge(knowledge_id: int):
        return {"id": knowledge_id}

    @app.get("/api/v2/chat")
    async def chat():
        return {"ok": True}

    @app.get("/api/v1/admin/api-rate-limit/routes", tags=["api-rate-limit"])
    async def route_catalog():
        return {"items": []}

    @app.websocket("/api/v1/ws")
    async def websocket_route(websocket: WebSocket):
        await websocket.accept()

    return app.router.routes


def test_catalog_classifies_deduplicates_and_excludes_non_limitable_routes():
    catalog = ApiRouteCatalogService.list_routes(_build_routes(), page_size=100)

    identities = {(item.method.value, item.path) for item in catalog.items}
    assert identities == {
        ("GET", "/api/v1/knowledge/{knowledge_id}"),
        ("POST", "/api/v1/knowledge/{knowledge_id}"),
        ("GET", "/api/v2/chat"),
    }
    assert catalog.categories == ["Knowledge", UNCATEGORIZED_ROUTE_TAG]
    assert next(item for item in catalog.items if item.path == "/api/v2/chat").primary_tag == UNCATEGORIZED_ROUTE_TAG


def test_catalog_supports_keyword_method_tag_and_pagination_queries():
    routes = _build_routes()

    keyword_result = ApiRouteCatalogService.list_routes(routes, keyword="查询知识库")
    method_result = ApiRouteCatalogService.list_routes(routes, method=HttpMethod.POST)
    tag_result = ApiRouteCatalogService.list_routes(routes, tag="admin")
    paged_result = ApiRouteCatalogService.list_routes(routes, page=2, page_size=1)

    assert [(item.method.value, item.path) for item in keyword_result.items] == [
        ("GET", "/api/v1/knowledge/{knowledge_id}")
    ]
    assert [(item.method.value, item.path) for item in method_result.items] == [
        ("POST", "/api/v1/knowledge/{knowledge_id}")
    ]
    assert [(item.method.value, item.path) for item in tag_result.items] == [
        ("POST", "/api/v1/knowledge/{knowledge_id}")
    ]
    assert paged_result.total == 3
    assert paged_result.total_pages == 3
    assert paged_result.page == 2
    assert len(paged_result.items) == 1
