"""AC-55/54: gateways prove business ownership; role binds remain subject-owned."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.admin.application import gateway_scope
from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.core.context.tenant import tenant_execution_scope


async def test_gateway_department_uses_business_owner_not_root_storage(monkeypatch):
    monkeypatch.setattr(
        gateway_scope,
        "resolve_verified_department_scope",
        AsyncMock(return_value=SimpleNamespace(business_tenant_id=60, storage_tenant_id=1)),
    )
    with tenant_execution_scope(60):
        result = await gateway_scope.authorize_gateway_targets(SimpleNamespace(user_id=191), department_id=20)
    assert result["tenant_id"] == 60
    with tenant_execution_scope(65), pytest.raises(PermissionInvalidResourceError):
        await gateway_scope.authorize_gateway_targets(SimpleNamespace(user_id=191), department_id=20)


async def test_super_cannot_bind_a_foreign_home_through_a_tenant_page(monkeypatch):
    from bisheng.common.errcode.role import RolePermissionDeniedError
    from bisheng.common.request_scope import admitted_request_scope
    from bisheng.user.api import user as endpoint
    from bisheng.user.application import policy_bindings

    monkeypatch.setattr(
        policy_bindings, "read_policy_subject", AsyncMock(return_value=SimpleNamespace(home_tenant_id=65))
    )
    save = AsyncMock()
    monkeypatch.setattr(policy_bindings, "replace_policy_bindings", save)
    token = admitted_request_scope.set(SimpleNamespace(user_id=191, tenant_id=60))
    try:
        with pytest.raises(RolePermissionDeniedError):
            await endpoint.user_addrole(
                request=object(),
                user_role=endpoint.UserRoleCreate(user_id=7, role_id=[3]),
                login_user=SimpleNamespace(user_id=191, tenant_id=1, is_admin=lambda: True),
            )
        save.assert_not_awaited()
    finally:
        admitted_request_scope.reset(token)


@pytest.mark.parametrize("operation", ["create", "list"])
async def test_legacy_role_routes_do_not_fall_back_after_service_failure(monkeypatch, operation):
    from bisheng.role.domain.services.role_service import RoleService
    from bisheng.user.api import user as endpoint

    failing = AsyncMock(side_effect=RuntimeError("unknown primary outcome"))
    if operation == "create":
        monkeypatch.setattr(RoleService, "create_role", failing)
        with pytest.raises(RuntimeError, match="unknown primary outcome"):
            await endpoint.create_role(
                request=object(),
                role=endpoint.RoleCreate(role_name="local", group_id=1),
                login_user=SimpleNamespace(user_id=191),
            )
    else:
        monkeypatch.setattr(RoleService, "list_roles", failing)
        with pytest.raises(RuntimeError, match="unknown primary outcome"):
            await endpoint.get_role(login_user=SimpleNamespace(user_id=191))
