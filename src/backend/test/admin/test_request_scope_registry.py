"""AC-49/50: route groups inherit policy and exceptions fail closed."""

import pytest
from fastapi import APIRouter, FastAPI

from bisheng.common.request_scope import RequestScope, ScopedAPIRouter, request_scope, route_inventory


def test_new_child_endpoint_inherits_the_business_group():
    child = APIRouter()

    @child.get("/new-resource")
    def resource():
        return {}

    root = ScopedAPIRouter()
    root.include_router(child, request_scope=RequestScope.TENANT)
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.include_router(root)
    assert route_inventory(app.routes)[0]["scope"] == "tenant"


def test_explicit_identity_exception_and_missing_registration():
    child = APIRouter()

    @child.get("/identity")
    @request_scope(RequestScope.IDENTITY)
    def identity():
        return {}

    root = ScopedAPIRouter()
    root.include_router(child, request_scope=RequestScope.TENANT)
    assert route_inventory(root.routes)[0]["scope"] == "identity"
    with pytest.raises(ValueError, match="unregistered"):
        route_inventory([*APIRouter().routes, type("Route", (), {"endpoint": lambda: None, "path": "/forgotten"})()])


def test_an_undeclared_new_router_is_not_silently_tenant_or_global():
    root = ScopedAPIRouter()
    child = APIRouter()

    @child.get("/unknown")
    def unknown():
        return {}

    with pytest.raises(ValueError, match="scope"):
        root.include_router(child)


def test_actual_application_has_complete_scope_registration():
    from bisheng.main import app

    rows = route_inventory(app.routes)
    assert rows and all(row["scope"] for row in rows)
    assert next(row for row in rows if row["path"] == "/api/v1/user/profile/nickname")["scope"] == "identity"
    assert {"tenant", "identity", "platform", "personal", "public", "credential"} <= {row["scope"] for row in rows}


def test_frontend_scope_metadata_matches_the_actual_backend():
    import json
    from pathlib import Path

    from bisheng.main import app

    target = Path(__file__).resolve().parents[3] / "frontend/packages/api-client/src/requestScopeRoutes.json"
    assert json.loads(target.read_text()) == json.loads(
        json.dumps(
            [{key: row[key] for key in ("method", "path", "scope", "variant")} for row in route_inventory(app.routes)]
        )
    )


def test_query_exception_cannot_silently_refer_to_a_renamed_endpoint():
    from bisheng.common.request_scope import scope_query_variant

    with pytest.raises(ValueError, match="Unknown scope variants"):
        scope_query_variant(APIRouter(), ["missing"], query="purpose", value="approval", kind=RequestScope.IDENTITY)
