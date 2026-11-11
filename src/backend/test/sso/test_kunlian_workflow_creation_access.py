"""F130: 专属创建权不能放大为通用应用创建权。"""

# 覆盖 AC: AC-03, AC-04, AC-06, AC-13

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from bisheng.approval.domain.services.user_menu_access_service import UserMenuAccessService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.database.models.flow import Flow
from bisheng.database.models.role_access import RoleAccessDao
from bisheng.user.domain.models.user_role import UserRoleDao
from bisheng.user.domain.services.auth import AuthJwt, DepartmentDao, LoginUser, UserDao


@pytest.fixture
async def creation_api(monkeypatch):
    from bisheng.api.v1 import assistant, workflow
    from bisheng.workflow.application import kunlian_workflow_creation

    user = UserPayload(user_id=42, user_name="fixture", tenant_id=7, user_role=[])
    menus = []
    monkeypatch.setattr(LoginUser, "get_login_user", AsyncMock(return_value=user))
    monkeypatch.setattr(UserDao, "aget_user", AsyncMock(return_value=SimpleNamespace(user_id=42)))
    monkeypatch.setattr(DepartmentDao, "aget_user_admin_departments", AsyncMock(return_value=[]))
    monkeypatch.setattr(UserRoleDao, "aget_user_roles", AsyncMock(return_value=[SimpleNamespace(role_id=91)]))
    monkeypatch.setattr(
        RoleAccessDao,
        "aget_role_access",
        AsyncMock(side_effect=lambda *a: [SimpleNamespace(third_id=m) for m in menus]),
    )
    monkeypatch.setattr(UserMenuAccessService, "list_effective_menu_grants", AsyncMock(return_value=[]))
    row = Flow(id="f" * 32, name="fixture", user_id=42, tenant_id=7, flow_type=10, status=1)
    create = AsyncMock(return_value=(row, 1))
    monkeypatch.setattr(kunlian_workflow_creation, "create_registered_workflow", create)
    app = FastAPI()
    app.include_router(workflow.router, prefix="/api/v1")
    app.include_router(assistant.router, prefix="/api/v1")
    app.dependency_overrides[AuthJwt] = lambda: MagicMock()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
        yield client, menus, create


@pytest.mark.parametrize("menu", ["create_workflow", "create_app"])
async def test_current_workflow_or_legacy_app_permission_can_create(creation_api, menu):
    client, menus, create = creation_api
    menus.extend(["admin", "build", menu])
    response = await client.post(
        "/api/v1/workflow/create?scope=workflow_management",
        json={"name": "fixture", "flow_type": 10},
        headers={"Idempotency-Key": "same-creation"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["flow_type"] == 10
    create.assert_awaited_once()

    # 旧回执存在也不能绕过已经撤销的当前资格。
    menus.clear()
    response = await client.post(
        "/api/v1/workflow/create?scope=workflow_management",
        json={"name": "fixture", "flow_type": 10},
        headers={"Idempotency-Key": "same-creation"},
    )
    assert response.status_code == 403
    assert create.await_count == 1


async def test_scope_does_not_grant_creation_and_workflow_permission_does_not_create_assistants(creation_api):
    client, menus, create = creation_api
    menus.extend(["admin", "build"])
    response = await client.post("/api/v1/workflow/create?scope=workflow_management", json={"name": "fixture"})
    assert response.status_code == 403
    menus.append("create_workflow")
    response = await client.post("/api/v1/assistant", json={"name": "fixture", "prompt": "fixture"})
    assert response.status_code == 403, response.text
    create.assert_not_awaited()


async def test_invalid_session_is_rejected_before_menu_or_creation(creation_api, monkeypatch):
    client, menus, create = creation_api
    menus.extend(["admin", "build", "create_workflow"])
    monkeypatch.setattr(LoginUser, "get_login_user", AsyncMock(side_effect=HTTPException(status_code=401)))
    response = await client.post("/api/v1/workflow/create?scope=workflow_management", json={"name": "fixture"})
    assert response.status_code == 401
    create.assert_not_awaited()


@pytest.mark.parametrize("parents", [[], ["admin"], ["build"]])
async def test_workflow_permission_requires_current_parent_menus(creation_api, parents):
    client, menus, create = creation_api
    menus.extend([*parents, "create_workflow"])
    response = await client.post("/api/v1/workflow/create?scope=workflow_management", json={"name": "fixture"})
    assert response.status_code == 403, response.text
    create.assert_not_awaited()


@pytest.mark.parametrize("flow_type", [5, 35])
async def test_workflow_endpoint_refuses_other_types_before_creation(creation_api, flow_type):
    client, menus, create = creation_api
    menus.extend(["admin", "build", "create_app"])
    response = await client.post(
        "/api/v1/workflow/create?scope=workflow_management",
        json={"name": "fixture", "flow_type": flow_type},
        headers={"Idempotency-Key": "same-creation"},
    )
    assert response.status_code == 422, response.text
    create.assert_not_awaited()
