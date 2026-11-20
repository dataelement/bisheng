"""Directory display follows the release-line v3.0.0 existing-grant policy."""

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
    assert {role["id"] for role in result[77]["roles"]} == {2, 3, 4, 5}
    assert result[77]["role_binding_issues"] == []


async def test_only_missing_definitions_are_issues_and_existing_person_grants_stay_visible(policy_db):
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
    assert reasons == {"definition_missing"}
    assert {r["id"] for r in result[77]["roles"]} == {2, 3, 4, 5, 7, 8}
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


async def test_display_matches_existing_grant_policy_for_super_and_ordinary_views(policy_db):
    from bisheng.role.application.effective_roles import load_effective_roles

    with tenant_execution_scope(2):
        expected = await load_effective_roles(77, expected_home_tenant_id=2)
        for include_issues in (False, True):
            result = await read_member_role_display({77}, tenant_id=2, include_issues=include_issues)
            assert tuple(role["id"] for role in result[77]["roles"]) == expected.role_ids
            if include_issues:
                assert result[77]["role_binding_issues"] == []
            else:
                assert "role_binding_issues" not in result[77]
