"""All route scenarios share the same verified applicant role labels."""

from unittest.mock import AsyncMock

import pytest

from bisheng.approval.domain.services.approval_gate import _get_user_role_labels
from bisheng.common.errcode.role import RolePolicyUnavailableError
from bisheng.core.context.tenant import tenant_execution_scope
from test.fixtures.managed_tenant import managed_db as managed_db
from test.role.test_effective_roles import policy_db as policy_db


@pytest.mark.parametrize(
    "scenario", ["menu_access", "channel_subscribe", "knowledge_space_join", "app_publish_request"]
)
async def test_current_roles_in_each_route_scenario(policy_db, monkeypatch, scenario):
    from bisheng.database.models.department import DepartmentDao
    from bisheng.tenant.domain.services.tenant_service import TenantService

    monkeypatch.setattr(DepartmentDao, "aget_user_admin_departments", AsyncMock(return_value=[]))
    monkeypatch.setattr(TenantService, "_is_tenant_admin", AsyncMock(return_value=False))
    with tenant_execution_scope(2):
        assert await _get_user_role_labels(77, 2) == {"regular_user", "admin", "role_2", "role_3"}


async def test_policy_failure_does_not_match_regular_user_route(policy_db, monkeypatch):
    from bisheng.role.application import effective_roles

    monkeypatch.setattr(effective_roles, "load_effective_roles", AsyncMock(side_effect=RolePolicyUnavailableError()))
    with pytest.raises(RolePolicyUnavailableError):
        await _get_user_role_labels(77, 2)
