"""F009 AC-04..07: B-based candidates and rejection before any mixed writes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlmodel import delete, select

from bisheng.common.errcode.department import DepartmentInvalidRolesError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.database.models.department import Department
from bisheng.database.models.role import Role
from bisheng.database.models.user_role import UserRole
from bisheng.department.domain.schemas.department_schema import DepartmentMemberEditApply
from bisheng.department.domain.services.department_service import DepartmentService
from bisheng.user.domain.models.user import User
from test.fixtures.managed_tenant import managed_db as managed_db
from test.role.test_effective_roles import policy_db as policy_db


@pytest.fixture
async def member_db(policy_db, monkeypatch):
    import bisheng.database.models.department as departments
    import bisheng.department.domain.services.department_service as module
    import bisheng.user.domain.models.user as users
    import bisheng.user.domain.models.user_role as bindings

    for target in (departments, module, users, bindings):
        monkeypatch.setattr(target, "get_async_db_session", policy_db.sessions)
    for target in (users, bindings):
        monkeypatch.setattr(target, "get_sync_db_session", policy_db.sync_sessions)
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            await session.exec(delete(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 1))
            session.add(Role(id=7, role_name="Root custom", role_type="tenant", tenant_id=1))
            await session.commit()
    from bisheng.user.domain.services.nickname_service import NicknameService

    monkeypatch.setattr(NicknameService, "arecord_failure", AsyncMock())
    return policy_db


def actor():
    return SimpleNamespace(user_id=7, tenant_id=1, user_role=[1], is_admin=lambda: True)


async def test_single_and_batch_candidates_use_mounted_business_not_actor(member_db):
    """AC-04: S=Root and actor H=Root do not hide child tenant definitions."""
    with tenant_execution_scope(1):
        single = await DepartmentService.aget_assignable_roles("a-leaf", actor())
        async with member_db.sessions() as session:
            depts = (await session.exec(select(Department).where(Department.id.in_([30, 40])))).all()
        batch = await DepartmentService._aget_assignable_roles_catalog(depts, actor())
    assert {row["id"] for row in single} == {2, 3}
    assert {row["id"] for row in batch["a-leaf"]} == {2, 3}
    assert {row["id"] for row in batch["b"]} == {2, 4, 5}


async def test_foreign_affiliate_policy_rejected_before_role_write(member_db, monkeypatch):
    """AC-05/06: a global definition is not a foreign-tenant grant."""
    from bisheng.user.domain.models.user_role import UserRoleDao

    write = Mock(side_effect=AssertionError("role write before foreign-policy validation"))
    monkeypatch.setattr(UserRoleDao, "add_user_roles", write)
    with tenant_execution_scope(1), pytest.raises(DepartmentInvalidRolesError):
        await DepartmentService.aapply_member_edit(
            "b", 77, DepartmentMemberEditApply(context_role_ids=[2], user_name="changed", group_ids=[]), actor()
        )
    write.assert_not_called()


async def test_invalid_primary_roles_do_not_commit_name_first(member_db):
    """AC-06: final role qualification precedes earlier name/group commits."""
    with tenant_execution_scope(1), pytest.raises(DepartmentInvalidRolesError):
        await DepartmentService.aapply_member_edit(
            "a-leaf", 77, DepartmentMemberEditApply(user_name="changed", primary_role_ids=[4]), actor()
        )
    with bypass_tenant_filter():
        async with member_db.sessions() as session:
            assert (await session.get(User, 77)).user_name == "policy"


async def test_foreign_affiliate_form_does_not_show_home_role_bindings(member_db, monkeypatch):
    """AC-05/07: same role ID in a foreign catalog must not look granted there."""
    from bisheng.database.models.user_group import UserGroupDao

    monkeypatch.setattr(UserGroupDao, "aget_user_group", AsyncMock(return_value=[]))
    monkeypatch.setattr(UserGroupDao, "aget_user_admin_group", AsyncMock(return_value=[]))
    monkeypatch.setattr(DepartmentService, "_manageable_group_options", AsyncMock(return_value=[]))
    with tenant_execution_scope(1):
        form = await DepartmentService.aget_member_edit_form("b", 77, actor())
    assert form["policy_editable"] is False
    assert form["role_apply_status"] == "NOT_APPLICABLE_CROSS_TENANT"
    assert form["context_role_ids"] == []
    assert form["assignable_roles_catalog"]["b"] == []


async def test_stale_home_policy_edit_rejected_before_name_commit(member_db):
    from bisheng.common.errcode.role import RolePolicyUnavailableError
    from bisheng.database.models.tenant import UserTenant

    with bypass_tenant_filter():
        async with member_db.sessions() as session:
            (await session.get(UserTenant, 1)).tenant_id = 3
            await session.commit()
    with tenant_execution_scope(1), pytest.raises(RolePolicyUnavailableError):
        await DepartmentService.aapply_member_edit(
            "a-leaf", 77, DepartmentMemberEditApply(user_name="changed", primary_role_ids=[2]), actor()
        )
    with bypass_tenant_filter():
        async with member_db.sessions() as session:
            assert (await session.get(User, 77)).user_name == "policy"
