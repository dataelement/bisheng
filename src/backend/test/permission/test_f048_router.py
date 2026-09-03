"""Router-level contract for the F048 permission HTTP surface."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.permission.api.dependencies import (
    get_catalog_api,
    get_permission_decision_api,
    get_resource_permission_api,
)
from bisheng.permission.api.router import router


class _Catalog:
    async def get_current(self):
        return {"id": 12, "status": "CURRENT"}


class _Resource:
    async def get_context(self, **kwargs):
        return {
            "mode": "CUSTOM",
            "resource_version": 1,
            "projection_state": "ACTIVE",
        }


class _Decision:
    async def check(self, **kwargs):
        return True


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: UserPayload(
        user_id=1,
        user_name="root",
        user_role=[],
        tenant_id=1,
        is_global_super=True,
    )
    app.dependency_overrides[get_catalog_api] = lambda: _Catalog()
    app.dependency_overrides[get_resource_permission_api] = lambda: _Resource()
    app.dependency_overrides[get_permission_decision_api] = lambda: _Decision()
    return app


def test_f048_routes_are_registered_with_auth_and_unified_responses() -> None:
    app = _app()
    paths = {route.path: route for route in app.routes if route.path.startswith("/api/v1/permissions")}
    expected = {
        "/api/v1/permissions/catalog",
        "/api/v1/permissions/catalog/drafts",
        "/api/v1/permissions/catalog/drafts/{draft_id}",
        "/api/v1/permissions/catalog/drafts/{draft_id}/publish",
        ("/api/v1/permissions/resources/{resource_type}/{resource_id}/grantable-models"),
        ("/api/v1/permissions/resources/{resource_type}/{resource_id}/context"),
        ("/api/v1/permissions/resources/{resource_type}/{resource_id}/grants"),
        ("/api/v1/permissions/resources/{resource_type}/{resource_id}/my-permissions"),
        ("/api/v1/permissions/resources/{resource_type}/{resource_id}/grants:mutate"),
        ("/api/v1/permissions/resources/{resource_type}/{resource_id}/mode-drafts"),
        ("/api/v1/permissions/resources/{resource_type}/{resource_id}/mode-drafts/{draft_id}/apply"),
        "/api/v1/permissions/check",
    }
    assert expected <= paths.keys()
    assert all(
        any(dependency.call == UserPayload.get_login_user for dependency in paths[path].dependant.dependencies)
        for path in expected
    )

    with TestClient(app) as client:
        catalog = client.get("/api/v1/permissions/catalog").json()
        context = client.get("/api/v1/permissions/resources/knowledge_file/file-1/context").json()
        decision = client.post(
            "/api/v1/permissions/check",
            json={
                "resource_type": "knowledge_file",
                "resource_id": "file-1",
                "action": "download",
            },
        ).json()

    assert catalog["status_code"] == 200
    assert context["status_code"] == 200
    assert decision == {
        "status_code": 200,
        "status_message": "SUCCESS",
        "data": {"allowed": True},
    }


def test_legacy_routes_are_not_reachable_and_alias_payload_is_rejected() -> None:
    with TestClient(_app()) as client:
        for method, path in (
            ("get", "/api/v1/permissions/objects"),
            ("get", "/api/v1/permissions/relation-models"),
            (
                "post",
                "/api/v1/permissions/resources/workflow/wf-1/authorize",
            ),
        ):
            response = client.request(method, path)
            assert response.status_code == 404

        legacy = client.post(
            "/api/v1/permissions/check",
            json={
                "object_type": "workflow",
                "object_id": "wf-1",
                "relation": "can_read",
                "permission_id": "view_app",
            },
        )

    assert legacy.status_code == 200
    assert legacy.json()["status_code"] == 25001
