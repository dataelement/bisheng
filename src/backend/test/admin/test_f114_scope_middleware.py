"""F114 AC-15/16/18: scope is pinned and old management writes are refused."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


@pytest.fixture
def scoped_client(monkeypatch):
    from bisheng.admin.application import tenant_scope as port
    from bisheng.common.middleware import admin_scope as middleware
    from bisheng.core.context.tenant import get_admin_scope_tenant_id, get_visible_tenant_ids, is_management_all_tenants

    super_check = AsyncMock(return_value=True)
    resolver = AsyncMock(return_value=port.EffectiveManagementScope(3, "selected", None))
    monkeypatch.setattr(middleware, "_extract_http_access_token", lambda request: "authenticated")
    monkeypatch.setattr(middleware, "_decode_jwt_subject", lambda token: {"user_id": 42, "tenant_id": 2})
    monkeypatch.setattr(middleware, "_check_is_global_super", super_check)
    monkeypatch.setattr(port, "resolve_management_scope", resolver)
    app = FastAPI()
    app.add_middleware(middleware.AdminScopeMiddleware)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"])
    async def echo(request: Request, path: str):
        return {
            "scope": get_admin_scope_tenant_id(),
            "visible": sorted(get_visible_tenant_ids() or []),
            "all": is_management_all_tenants(),
        }

    with TestClient(app) as client:
        yield client, resolver, super_check


def test_shared_read_has_no_new_required_header(scoped_client):
    client, _resolver, _super_check = scoped_client
    response = client.get("/api/v1/knowledge/3")
    assert response.status_code == 200
    assert response.json() == {"scope": 3, "visible": [3], "all": False}
    assert response.headers["X-Management-Tenant"] == "3"


@pytest.mark.parametrize("header,code", [({}, 19703), ({"X-Management-Tenant": "2"}, 19704)])
def test_old_form_never_executes_in_new_scope(scoped_client, header, code):
    client, _resolver, _super_check = scoped_client
    response = client.patch("/api/v1/apps/target", headers=header, json={"name": "changed"})
    assert response.json()["status_code"] == code


def test_matching_form_pins_the_scope(scoped_client):
    client, resolver, _super_check = scoped_client
    response = client.post("/api/v1/apps/target/actions/stop", headers={"X-Management-Tenant": "3"})
    assert response.status_code == 200
    assert response.json()["scope"] == 3
    assert resolver.await_args.kwargs["for_write"] is True


@pytest.mark.parametrize(
    "path", ["/api/v2/apps/deploy", "/api/v1/internal/app-runtime/v2/routes/app", "/api/v1/approval/user/tasks"]
)
def test_execution_and_personal_tasks_do_not_inherit_browser_scope(scoped_client, path):
    client, resolver, super_check = scoped_client
    assert client.get(path).json()["scope"] is None
    resolver.assert_not_awaited()
    super_check.assert_not_awaited()


def test_service_account_old_header_is_still_legal(scoped_client):
    client, _resolver, _super_check = scoped_client
    assert client.post("/api/v1/service-accounts", headers={"X-Service-Account-Tenant": "3"}).status_code == 200
    response = client.post(
        "/api/v1/service-accounts", headers={"X-Service-Account-Tenant": "3", "X-Management-Tenant": "2"}
    )
    assert response.json()["status_code"] == 26073
