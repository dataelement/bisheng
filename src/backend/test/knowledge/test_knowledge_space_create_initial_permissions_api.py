from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.api.dependencies import (
    get_knowledge_space_creation_application_service,
    get_knowledge_space_service,
)
from bisheng.knowledge.api.endpoints.knowledge_space import router
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.role.domain.services.quota_service import QuotaService


class _User:
    user_id = 7
    user_name = "creator"
    tenant_id = 3
    user_role = []


class _LegacyServiceGuard:
    async def create_knowledge_space(self, **_):
        raise AssertionError("create endpoint bypassed the application service")


@pytest.fixture
def app_with_creation_service(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    service = AsyncMock()
    service.create.return_value = Knowledge(
        id=101,
        name="Alpha",
        user_id=7,
        tenant_id=3,
        type=KnowledgeTypeEnum.SPACE.value,
    )

    async def get_user():
        return _User()

    async def get_application_service():
        return service

    async def get_legacy_service_guard():
        return _LegacyServiceGuard()

    async def handle_error(_request, error: BaseErrorCode):
        return JSONResponse(status_code=200, content=error.to_dict())

    app.dependency_overrides[UserPayload.get_login_user] = get_user
    app.dependency_overrides[get_knowledge_space_creation_application_service] = get_application_service
    app.dependency_overrides[get_knowledge_space_service] = get_legacy_service_guard
    app.add_exception_handler(BaseErrorCode, handle_error)
    monkeypatch.setattr(QuotaService, "check_quota", AsyncMock())
    return app, service


def _create(client: TestClient, payload: dict):
    return client.post("/api/v1/knowledge/space", json=payload)


def test_create_space_old_payload_delegates_and_keeps_response(app_with_creation_service):
    app, service = app_with_creation_service

    with TestClient(app) as client:
        response = _create(client, {"name": "Alpha"})

    body = response.json()
    assert body["status_code"] == 200
    assert body["data"]["id"] == 101
    assert "initial_permission_result" not in body["data"]
    service.create.assert_awaited_once()
    create_request = service.create.await_args.kwargs["req"]
    assert create_request.name == "Alpha"
    assert create_request.initial_permissions is None


def test_create_space_with_initial_grants_returns_success(app_with_creation_service):
    app, service = app_with_creation_service
    service.create.return_value = {
        "id": 101,
        "name": "Alpha",
        "initial_permission_result": {"status": "success", "error_code": None},
    }

    with TestClient(app) as client:
        response = _create(
            client,
            {
                "name": "Alpha",
                "initial_permissions": {
                    "grants": [
                        {
                            "subject_type": "user",
                            "subject_id": 42,
                            "relation": "editor",
                            "include_children": False,
                            "model_id": "editor",
                        }
                    ]
                },
            },
        )

    body = response.json()
    assert body["status_code"] == 200
    assert body["data"]["id"] == 101
    assert body["data"]["initial_permission_result"] == {
        "status": "success",
        "error_code": None,
    }
    create_request = service.create.await_args.kwargs["req"]
    assert create_request.initial_permissions.grants[0].subject_id == 42
    assert create_request.initial_permissions.grants[0].relation == "editor"


def test_create_space_preserves_failed_grant_result(app_with_creation_service):
    app, service = app_with_creation_service
    service.create.return_value = {
        "id": 101,
        "name": "Alpha",
        "initial_permission_result": {
            "status": "failed",
            "error_code": PermissionDeniedError.Code,
        },
    }

    with TestClient(app) as client:
        response = _create(
            client,
            {
                "name": "Alpha",
                "initial_permissions": {"grants": [{"subject_type": "user", "subject_id": 42, "relation": "viewer"}]},
            },
        )

    assert response.json()["data"] == service.create.return_value
    service.create.assert_awaited_once()


def test_initial_permissions_rejects_revokes(app_with_creation_service):
    app, service = app_with_creation_service

    with TestClient(app) as client:
        response = _create(
            client,
            {
                "name": "Alpha",
                "initial_permissions": {"grants": [], "revokes": []},
            },
        )

    assert response.status_code == 422
    service.create.assert_not_awaited()


@pytest.mark.parametrize("subject_type", ["department", "user_group"])
def test_non_user_owner_rejection_uses_existing_error_envelope(
    app_with_creation_service,
    subject_type: str,
):
    app, service = app_with_creation_service
    service.create.side_effect = PermissionDeniedError()

    with TestClient(app) as client:
        response = _create(
            client,
            {
                "name": "Alpha",
                "initial_permissions": {
                    "grants": [{"subject_type": subject_type, "subject_id": 9, "relation": "owner"}]
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["status_code"] == PermissionDeniedError.Code
    service.create.assert_awaited_once()
