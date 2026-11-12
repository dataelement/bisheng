"""F009 AC-04/07/15/16/18: one ordinary policy, independent of M."""

import pytest

from bisheng.common.errcode.role import RolePolicyUnavailableError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.role import Role
from bisheng.database.models.role_access import RoleAccess
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.database.models.user_role import UserRole
from bisheng.user.domain.models.user import User
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope


@pytest.fixture
async def policy_db(managed_db, monkeypatch):
    from bisheng.department.domain.repositories import policy_scope_repository
    from bisheng.role.domain.repositories import effective_role_repository
    from bisheng.user.domain.repositories import policy_binding_repository

    await managed_db.create(User, Tenant, Department, UserDepartment, UserTenant, Role, UserRole, RoleAccess)
    import bisheng.database.models.department as department_models

    for module in (policy_scope_repository, effective_role_repository, policy_binding_repository, department_models):
        monkeypatch.setattr(module, "get_async_db_session", managed_db.sessions)
        monkeypatch.setattr(module, "get_sync_db_session", managed_db.sync_sessions)
    with bypass_tenant_filter():
        async with managed_db.sessions() as session:
            session.add_all(
                [
                    User(user_id=77, user_name="policy", password="fixture-only"),
                    User(user_id=78, user_name="empty", password="fixture-only"),
                    Tenant(id=1, tenant_code="root", tenant_name="Root", root_dept_id=10),
                    Tenant(id=2, tenant_code="a", tenant_name="A", root_dept_id=20, parent_tenant_id=1),
                    Tenant(id=3, tenant_code="b", tenant_name="B", root_dept_id=40, parent_tenant_id=1),
                    Department(id=10, dept_id="root", name="Root", tenant_id=1, path="/10/"),
                    Department(
                        id=20,
                        dept_id="a",
                        name="A",
                        tenant_id=1,
                        parent_id=10,
                        path="/10/20/",
                        is_tenant_root=1,
                        mounted_tenant_id=2,
                    ),
                    Department(id=30, dept_id="a-leaf", name="leaf", tenant_id=1, parent_id=20, path="/10/20/30/"),
                    Department(
                        id=40,
                        dept_id="b",
                        name="B",
                        tenant_id=1,
                        parent_id=10,
                        path="/10/40/",
                        is_tenant_root=1,
                        mounted_tenant_id=3,
                    ),
                    UserTenant(id=1, user_id=77, tenant_id=2, is_active=1),
                    UserTenant(id=2, user_id=78, tenant_id=1, is_active=1),
                    UserDepartment(id=1, user_id=77, department_id=30, is_primary=1),
                    UserDepartment(id=2, user_id=77, department_id=40, is_primary=0),
                    Role(id=2, role_name="global", role_type="global", tenant_id=1, quota_config={"channel": 0}),
                    Role(id=3, role_name="A", role_type="tenant", tenant_id=2, department_id=20),
                    Role(id=4, role_name="B", role_type="tenant", tenant_id=3, department_id=40),
                    Role(id=5, role_name="global B scoped", role_type="global", tenant_id=1, department_id=40),
                    RoleAccess(id=1, role_id=2, type=99, third_id="tool", tenant_id=1),
                    RoleAccess(id=2, role_id=2, type=99, third_id="wrong-owner", tenant_id=2),
                    RoleAccess(id=3, role_id=3, type=99, third_id="knowledge", tenant_id=2),
                    RoleAccess(id=4, role_id=2, type=1, third_id="resource-not-menu", tenant_id=1),
                ]
            )
            session.add_all(
                [
                    UserRole(id=i, user_id=77, role_id=role_id, tenant_id=home)
                    for i, (role_id, home) in enumerate([(2, 2), (3, 2), (4, 2), (5, 2), (2, 3), (3, 2), (1, 1)], 1)
                ]
            )
            await session.commit()
    return managed_db


async def test_home_policy_deduplicates_and_excludes_foreign_memberships(policy_db):
    """AC-04/07/15/16: foreign memberships and M cannot add roles."""
    from bisheng.role.application.effective_roles import load_effective_roles, load_effective_roles_sync

    with management_scope(home=2, target=3):
        result = await load_effective_roles(77, expected_home_tenant_id=2)
        assert result.home_tenant_id == 2
        assert result.role_ids == (2, 3)
        assert result.is_identity_admin
        assert result.web_menu == frozenset({"tool", "knowledge"})
        other = load_effective_roles_sync(77, expected_home_tenant_id=2)
        assert other.role_ids == result.role_ids and other.web_menu == result.web_menu


async def test_successful_empty_policy_is_not_failure(policy_db):
    """AC-18: verified no ordinary roles remains a valid empty policy."""
    from bisheng.role.application.effective_roles import load_effective_roles

    result = await load_effective_roles(78, expected_home_tenant_id=1)
    assert result.role_ids == () and not result.is_identity_admin


async def test_missing_bound_definition_is_not_empty_policy(policy_db):
    """AC-18: incomplete definitions cannot become default quota / no approval."""
    from bisheng.role.application.effective_roles import load_effective_roles

    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            session.add(UserRole(id=99, user_id=77, role_id=999, tenant_id=2))
            await session.commit()
    with pytest.raises(RolePolicyUnavailableError):
        await load_effective_roles(77)


async def test_stale_home_is_rejected(policy_db):
    """AC-13/18: current active home and verified execution identity must agree."""
    from bisheng.role.application.effective_roles import load_effective_roles

    with pytest.raises(RolePolicyUnavailableError):
        await load_effective_roles(77, expected_home_tenant_id=3)


async def test_disabled_foreign_affiliation_does_not_change_home_policy(policy_db):
    """AC-05: even a disabled foreign tenant cannot take over home decisions."""
    from bisheng.role.application.effective_roles import load_effective_roles

    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            (await session.get(Tenant, 3)).status = "disabled"
            await session.commit()
    assert (await load_effective_roles(77)).role_ids == (2, 3)
