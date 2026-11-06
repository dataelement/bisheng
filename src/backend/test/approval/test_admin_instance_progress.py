"""Management progress uses tenant administrator authority, not task ownership."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.approval.domain.models.approval_instance import ApprovalInstance
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.common.errcode.approval import ApprovalRequestPermissionDeniedError
from bisheng.core.context import tenant


@pytest.fixture
def pending(monkeypatch):
    instance = ApprovalInstance(
        id=433,
        tenant_id=2,
        scenario_code="app_publish_request",
        scenario_name="publish",
        business_key="app/v1",
        business_name="App",
        applicant_user_id=8,
        applicant_user_name="Owner",
        status="exception",
        create_time=datetime.now(),
        update_time=datetime.now(),
    )
    monkeypatch.setattr(ApprovalInstanceRepository, "get_instance", AsyncMock(return_value=instance))
    monkeypatch.setattr(ApprovalInstanceRepository, "list_tasks", AsyncMock(return_value=[]))
    monkeypatch.setattr(ApprovalInstanceRepository, "list_action_logs", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "bisheng.permission.application.is_tenant_admin", AsyncMock(side_effect=lambda uid, tid: uid == 7 and tid == 2)
    )
    return instance


async def test_tenant_admin_can_read_exception_without_approval_task(pending):
    user = SimpleNamespace(user_id=7, tenant_id=2, is_global_super=False, is_admin=lambda: False)
    with tenant.tenant_execution_scope(2):
        data = await ApprovalCenterService.get_instance_detail(instance_id=433, login_user=user, management=True)
        assert data["instance_id"] == 433
        with pytest.raises(ApprovalRequestPermissionDeniedError):
            await ApprovalCenterService.get_instance_detail(instance_id=433, login_user=user)


@pytest.mark.parametrize("tid,uid", [(3, 7), (2, 9)])
async def test_other_tenant_and_ordinary_member_cannot_read(pending, tid, uid):
    user = SimpleNamespace(user_id=uid, tenant_id=tid, is_global_super=False, is_admin=lambda: False)
    with tenant.tenant_execution_scope(tid), pytest.raises(ApprovalRequestPermissionDeniedError):
        await ApprovalCenterService.get_instance_detail(instance_id=433, login_user=user, management=True)


async def test_super_admin_selected_scope_controls_progress(pending):
    user = SimpleNamespace(user_id=1, tenant_id=1, is_global_super=True, is_admin=lambda: True)
    tokens = [(tenant._is_management_api, True), (tenant._admin_scope_tenant_id, 2)]
    resets = [(var, var.set(value)) for var, value in tokens]
    try:
        assert (await ApprovalCenterService.get_instance_detail(instance_id=433, login_user=user, management=True))[
            "instance_id"
        ] == 433
        tenant.set_admin_scope_tenant_id(3)
        with pytest.raises(ApprovalRequestPermissionDeniedError):
            await ApprovalCenterService.get_instance_detail(instance_id=433, login_user=user, management=True)
    finally:
        for var, token in reversed(resets):
            var.reset(token)


async def test_management_api_checks_tenant_admin_before_returning_progress(pending, monkeypatch):
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from bisheng.approval.api.endpoints.approval_admin import router
    from bisheng.common.dependencies.user_deps import UserPayload

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    actor = SimpleNamespace(user_id=7, tenant_id=2, is_global_super=False, is_admin=lambda: False)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: actor
    with tenant.tenant_execution_scope(2), TestClient(app) as client:
        result = client.get("/api/v1/approval/admin/instances/433")
        assert result.status_code == 200
        assert result.json()["data"]["instance_id"] == 433
        actor.user_id = 9
        assert client.get("/api/v1/approval/admin/instances/433").status_code == 403


async def test_global_list_never_supplies_an_implicit_write_tenant(pending):
    from bisheng.approval.api.endpoints.approval_admin import _tenant
    from bisheng.common.errcode.admin_scope import AdminScopeTenantRequiredError

    user = SimpleNamespace(user_id=1, tenant_id=1, is_global_super=True)
    bindings = [
        (tenant._is_management_api, True),
        (tenant._management_all_tenants, True),
        (tenant._admin_scope_tenant_id, None),
    ]
    tokens = [(var, var.set(value)) for var, value in bindings]
    try:
        assert _tenant(user, allow_all=True) is None
        with pytest.raises(AdminScopeTenantRequiredError):
            _tenant(user)
        tenant.set_admin_scope_tenant_id(2)
        assert _tenant(user) == 2
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
