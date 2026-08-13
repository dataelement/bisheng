"""F045 endpoint wiring tests for the department-space admin surface.

Mounts the knowledge_space router with the login dependency overridden and the
DepartmentKnowledgeSpaceService classmethods patched — validates URL, method,
payload plumbing and business-error mapping only (AC-01/02/05/06/11 API face).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import (
    SpaceAdminConflictError,
    SpaceAdminRequiredError,
)

_SERVICE = "bisheng.knowledge.domain.services.department_knowledge_space_service.DepartmentKnowledgeSpaceService"


def _fake_login_user():
    return SimpleNamespace(
        user_id=1,
        user_name="admin",
        tenant_id=1,
        is_admin=lambda: True,
    )


@pytest.fixture
def client():
    from bisheng.knowledge.api.endpoints.knowledge_space import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = _fake_login_user
    return TestClient(app)


def test_replace_admin_endpoint_plumbs_arguments(client):
    with patch(
        f"{_SERVICE}.replace_admin",
        new_callable=AsyncMock,
        return_value={"id": 101, "admin_user_id": 3},
    ) as mock_replace:
        r = client.put("/api/v1/knowledge/space/department/10/admin", json={"admin_user_id": 3})

    assert r.status_code == 200
    assert r.json()["status_code"] == 200
    kwargs = mock_replace.await_args.kwargs
    assert kwargs["department_id"] == 10
    assert kwargs["new_admin_user_id"] == 3


def test_replace_admin_endpoint_requires_admin_user_id(client):
    r = client.put("/api/v1/knowledge/space/department/10/admin", json={})
    assert r.status_code == 422  # pydantic required-field validation


def test_replace_admin_endpoint_maps_conflict_to_business_code(client):
    with patch(
        f"{_SERVICE}.replace_admin",
        new_callable=AsyncMock,
        side_effect=SpaceAdminConflictError(),
    ):
        r = client.put("/api/v1/knowledge/space/department/10/admin", json={"admin_user_id": 3})

    assert r.status_code == 200
    assert r.json()["status_code"] == SpaceAdminConflictError.Code  # 18006


def test_batch_create_maps_missing_admin_to_business_code(client):
    with patch(
        f"{_SERVICE}.batch_create_spaces",
        new_callable=AsyncMock,
        side_effect=SpaceAdminRequiredError(),
    ):
        r = client.post(
            "/api/v1/knowledge/space/department/batch-create",
            json={"items": [{"department_id": 10}]},
        )

    assert r.status_code == 200
    assert r.json()["status_code"] == SpaceAdminRequiredError.Code  # 18003


def test_batch_create_passes_admin_user_id_through(client):
    with patch(
        f"{_SERVICE}.batch_create_spaces",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_create:
        r = client.post(
            "/api/v1/knowledge/space/department/batch-create",
            json={"items": [{"department_id": 10, "admin_user_id": 2}]},
        )

    assert r.status_code == 200
    req = mock_create.await_args.kwargs["req"]
    assert req.items[0].admin_user_id == 2
