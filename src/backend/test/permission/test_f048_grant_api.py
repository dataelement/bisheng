"""HTTP contract tests for F048 resource Grant and mode endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import (
    PermissionVersionConflictError,
    ProtectedAssignmentMutationError,
)
from bisheng.permission.api.dependencies import get_resource_permission_api
from bisheng.permission.api.endpoints.grant import router


class _ResourcePermissionApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.error: Exception | None = None

    async def get_grantable_models(self, **kwargs) -> list[dict]:
        self.calls.append(("grantable", kwargs))
        return [
            {
                "key": "viewer",
                "name": "Viewer",
                "level": 1,
                "active": True,
            }
        ]

    async def get_context(self, **kwargs) -> dict:
        self.calls.append(("context", kwargs))
        return {
            "mode": "INHERIT",
            "parent_type": "folder",
            "parent_id": "root",
            "resource_version": 7,
            "projection_state": "ACTIVE",
            "can_manage_permission": True,
        }

    async def list_grants(self, **kwargs) -> dict:
        self.calls.append(("list_grants", kwargs))
        if self.error is not None:
            raise self.error
        return {
            "data": [
                {
                    "assignee_id": 91,
                    "assignee_version": 2,
                    "subject": {
                        "type": "department",
                        "id": "17",
                        "name": "R&D",
                    },
                    "model": {
                        "key": "viewer",
                        "name": "Viewer",
                        "level": 1,
                        "active": True,
                    },
                    "source": {
                        "type": "DEPARTMENT",
                        "include_children": True,
                    },
                    "scope": "INHERITED",
                    "inherited_from": "folder:root",
                    "protected": False,
                    "editable": False,
                }
            ],
            "page_size": kwargs["page_size"],
            "has_more": True,
            "next_cursor": "opaque-next",
        }

    async def get_my_permissions(self, **kwargs) -> dict:
        self.calls.append(("my_permissions", kwargs))
        return {
            "mode": "INHERIT",
            "actions": ["visible", "download"],
            "sources": [],
            "roster_complete": False,
        }

    async def mutate_grants(self, **kwargs) -> dict:
        self.calls.append(("mutate", kwargs))
        if self.error is not None:
            raise self.error
        return {"resource_version": 8, "items": []}

    async def create_mode_draft(self, **kwargs) -> dict:
        self.calls.append(("mode_draft", kwargs))
        return {
            "draft_id": "01KMODE",
            "target_mode": "CUSTOM",
            "impact_checksum": "d" * 64,
            "affected_assignees": 2,
            "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        }

    async def apply_mode_draft(self, **kwargs) -> dict:
        self.calls.append(("mode_apply", kwargs))
        return {
            "applied": True,
            "mode": "CUSTOM",
            "resource_version": 8,
        }


def _app(api: _ResourcePermissionApi) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/permissions")
    app.dependency_overrides[get_resource_permission_api] = lambda: api
    app.dependency_overrides[UserPayload.get_login_user] = lambda: UserPayload(
        user_id=7,
        user_name="member",
        user_role=[],
        tenant_id=5,
    )
    return app


def test_resource_context_models_roster_and_self_summary_contract() -> None:
    api = _ResourcePermissionApi()
    root = "/api/v1/permissions/resources/knowledge_file/file-1"
    with TestClient(_app(api)) as client:
        models = client.get(f"{root}/grantable-models").json()
        context = client.get(f"{root}/context").json()
        roster = client.get(
            f"{root}/grants",
            params={"cursor": "opaque-current", "page_size": 25},
        ).json()
        mine = client.get(f"{root}/my-permissions").json()

    assert models["data"][0]["key"] == "viewer"
    assert context["data"]["mode"] == "INHERIT"
    assert roster["data"]["data"][0]["editable"] is False
    assert roster["data"]["next_cursor"] == "opaque-next"
    assert mine["data"]["roster_complete"] is False
    assert api.calls[2][1]["cursor"] == "opaque-current"
    assert api.calls[2][1]["page_size"] == 25


def test_grant_mutation_forbids_server_owned_payload_fields() -> None:
    api = _ResourcePermissionApi()
    root = "/api/v1/permissions/resources/knowledge_file/file-1"
    payload = {
        "idempotency_key": "grant-1",
        "expected_resource_version": 7,
        "expected_catalog_release_id": 12,
        "changes": [
            {
                "op": "ADD",
                "model_key": "viewer",
                "subject": {"type": "user", "id": "8"},
                "protected": True,
                "source_type": "CREATOR",
                "level": 4,
            }
        ],
    }
    with TestClient(_app(api)) as client:
        response = client.post(f"{root}/grants:mutate", json=payload)

    assert response.status_code == 422
    assert not any(call[0] == "mutate" for call in api.calls)


def test_protected_mutation_and_stale_cursor_preserve_business_codes() -> None:
    api = _ResourcePermissionApi()
    root = "/api/v1/permissions/resources/knowledge_file/file-1"
    with TestClient(_app(api)) as client:
        api.error = PermissionVersionConflictError()
        stale = client.get(
            f"{root}/grants",
            params={"cursor": "other-resource", "page_size": 50},
        ).json()
        api.error = ProtectedAssignmentMutationError()
        protected = client.post(
            f"{root}/grants:mutate",
            json={
                "idempotency_key": "grant-2",
                "expected_resource_version": 7,
                "expected_catalog_release_id": 12,
                "changes": [
                    {
                        "op": "REMOVE",
                        "assignee_id": 91,
                        "expected_assignee_version": 2,
                    }
                ],
            },
        ).json()

    assert stale["status_code"] == 25002
    assert protected["status_code"] == 25006


def test_mode_draft_and_apply_only_send_server_draft_identity() -> None:
    api = _ResourcePermissionApi()
    root = "/api/v1/permissions/resources/knowledge_file/file-1"
    with TestClient(_app(api)) as client:
        draft = client.post(
            f"{root}/mode-drafts",
            json={
                "target_mode": "CUSTOM",
                "expected_resource_version": 7,
                "expected_catalog_release_id": 12,
            },
        ).json()
        applied = client.post(
            f"{root}/mode-drafts/01KMODE/apply",
            json={
                "idempotency_key": "mode-1",
                "expected_resource_version": 7,
                "expected_catalog_release_id": 12,
                "confirmed": True,
            },
        ).json()

    assert draft["data"]["draft_id"] == "01KMODE"
    assert applied["data"] == {
        "applied": True,
        "mode": "CUSTOM",
        "resource_version": 8,
    }
    apply_kwargs = api.calls[-1][1]
    assert apply_kwargs["draft_id"] == "01KMODE"
    assert "members" not in apply_kwargs
