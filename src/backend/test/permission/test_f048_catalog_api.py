"""HTTP contract tests for the F048 Catalog control plane."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import (
    ImmutableStandardModelError,
    InvalidCatalogActionError,
    PermissionVersionConflictError,
)
from bisheng.permission.api.dependencies import get_catalog_api
from bisheng.permission.api.endpoints.catalog import router


class _CatalogApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.error: Exception | None = None

    async def get_current(self) -> dict:
        self.calls.append(("get_current", None))
        return {
            "id": 12,
            "release_key": "catalog-v12",
            "version": 12,
            "status": "CURRENT",
            "authorization_model_id": "01HMODEL",
            "checksum": "a" * 64,
            "actions": [],
            "models": [],
        }

    async def create_draft(self, *, request, operator_id: int) -> dict:
        self.calls.append(("create_draft", (request, operator_id)))
        if self.error is not None:
            raise self.error
        return {
            "draft_id": 13,
            "base_release_id": request.base_release_id,
            "impact": {
                "checksum": "b" * 64,
                "resource_count": 2,
                "grant_count": 3,
                "assignee_count": 4,
                "expansion_count": 1,
                "revocation_count": 0,
                "blockers": [],
                "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            },
        }

    async def get_draft(self, *, draft_id: int, operator_id: int) -> dict:
        self.calls.append(("get_draft", (draft_id, operator_id)))
        return {"draft_id": draft_id, "owner_id": operator_id}

    async def publish_draft(
        self,
        *,
        draft_id: int,
        request,
        operator_id: int,
    ) -> dict:
        self.calls.append(("publish_draft", (draft_id, request, operator_id)))
        if self.error is not None:
            raise self.error
        return {
            "release_id": draft_id,
            "release_key": f"catalog-v{draft_id}",
            "status": "CURRENT",
            "release_checksum": "c" * 64,
        }


def _app(api: _CatalogApi, *, super_admin: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/permissions")
    app.dependency_overrides[get_catalog_api] = lambda: api
    app.dependency_overrides[UserPayload.get_login_user] = lambda: UserPayload(
        user_id=7,
        user_name="operator",
        user_role=[],
        tenant_id=1,
        is_global_super=super_admin,
    )
    return app


def test_catalog_get_and_draft_round_trip_use_unified_response() -> None:
    api = _CatalogApi()
    with TestClient(_app(api)) as client:
        current = client.get("/api/v1/permissions/catalog").json()
        created = client.post(
            "/api/v1/permissions/catalog/drafts",
            json={
                "idempotency_key": "draft-1",
                "base_release_id": 12,
                "changes": [
                    {
                        "type": "ASSIGN_ACTION_LEVEL",
                        "action_code": "edit",
                        "level": 2,
                    }
                ],
            },
        ).json()
        fetched = client.get("/api/v1/permissions/catalog/drafts/13").json()

    assert current["status_code"] == 200
    assert current["data"]["authorization_model_id"] == "01HMODEL"
    assert created["status_code"] == 200
    assert created["data"]["impact"]["resource_count"] == 2
    assert fetched == {
        "status_code": 200,
        "status_message": "SUCCESS",
        "data": {"draft_id": 13, "owner_id": 7},
    }


def test_catalog_requires_platform_super_admin() -> None:
    api = _CatalogApi()
    with TestClient(_app(api, super_admin=False)) as client:
        response = client.get("/api/v1/permissions/catalog")

    assert response.status_code == 200
    assert response.json()["status_code"] == 19000
    assert api.calls == []


def test_catalog_semantic_errors_are_translated_to_unified_codes() -> None:
    cases = (
        (InvalidCatalogActionError(), 25001),
        (ImmutableStandardModelError(), 25003),
    )
    for error, expected in cases:
        api = _CatalogApi()
        api.error = error
        with TestClient(_app(api)) as client:
            body = client.post(
                "/api/v1/permissions/catalog/drafts",
                json={
                    "idempotency_key": "draft-invalid",
                    "base_release_id": 12,
                    "changes": [
                        {
                            "type": "UPDATE_MODEL",
                            "model_key": "owner",
                            "name": "forbidden",
                            "action_codes": ["unknown-action"],
                        }
                    ],
                },
            ).json()
        assert body["status_code"] == expected


def test_catalog_publish_requires_confirmation_and_maps_version_conflict() -> None:
    api = _CatalogApi()
    with TestClient(_app(api)) as client:
        invalid = client.post(
            "/api/v1/permissions/catalog/drafts/13/publish",
            json={
                "expected_current_release_id": 12,
                "idempotency_key": "publish-1",
                "confirmed": False,
            },
        )
        api.error = PermissionVersionConflictError()
        conflicted = client.post(
            "/api/v1/permissions/catalog/drafts/13/publish",
            json={
                "expected_current_release_id": 12,
                "idempotency_key": "publish-2",
                "confirmed": True,
            },
        ).json()

    assert invalid.status_code == 422
    assert conflicted["status_code"] == 25002
