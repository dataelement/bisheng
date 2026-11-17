"""Directory display uses actual binding scope without repairing historical data."""

from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.database.models.role import Role
from bisheng.database.models.user_role import UserRole
from bisheng.role.application.member_role_display import read_member_role_display
from test.fixtures.managed_tenant import managed_db as managed_db
from test.role.test_effective_roles import policy_db as policy_db


async def test_valid_shared_and_tenant_roles_are_read_across_definition_storage(policy_db):
    with tenant_execution_scope(2):
        result = await read_member_role_display({77}, tenant_id=2, include_issues=True)
    assert {role["id"] for role in result[77]["roles"]} == {2, 3}
    assert result[77]["role_binding_issues"]


async def test_all_invalid_binding_reasons_are_diagnostic_only(policy_db):
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            session.add_all(
                [
                    Role(id=7, role_name="Root private", role_type="tenant", tenant_id=1),
                    Role(id=8, role_name="Foreign department", role_type="global", tenant_id=1, department_id=40),
                    UserRole(id=97, user_id=77, role_id=7, tenant_id=2),
                    UserRole(id=98, user_id=77, role_id=8, tenant_id=2),
                    UserRole(id=99, user_id=77, role_id=999, tenant_id=2),
                ]
            )
            await session.commit()
    with tenant_execution_scope(2):
        result = await read_member_role_display({77}, tenant_id=2, include_issues=True)
    reasons = {issue["reason"] for issue in result[77]["role_binding_issues"]}
    assert reasons == {
        "binding_tenant_mismatch",
        "definition_out_of_scope",
        "department_out_of_scope",
        "definition_missing",
    }
    assert {r["id"] for r in result[77]["roles"]} == {2, 3}
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            assert (await session.exec(select(UserRole).where(UserRole.id.in_([97, 98, 99])))).all()


async def test_non_super_response_omits_diagnostics_and_foreign_home_roles(policy_db):
    with tenant_execution_scope(2):
        result = await read_member_role_display({77, 78}, tenant_id=2)
    assert "role_binding_issues" not in result[77]
    assert result[78] == {"roles": []}


async def test_mismatched_business_target_is_rejected_before_reading(monkeypatch):
    from bisheng.role.application import member_role_display as module

    read = AsyncMock()
    monkeypatch.setattr(module, "read_directory_policy_subjects", read)
    with tenant_execution_scope(2), pytest.raises(ValueError):
        await read_member_role_display({77}, tenant_id=3, include_issues=True)
    read.assert_not_awaited()
