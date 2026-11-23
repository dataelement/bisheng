"""Upgrade compatibility uses original grants without changing resource boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlmodel import select

from bisheng.common.errcode.role import RolePolicyUnavailableError
from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter, tenant_execution_scope
from bisheng.database.models.department import Department, DepartmentDao, UserDepartment
from bisheng.database.models.flow import Flow
from bisheng.database.models.role import Role
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.database.models.user_group import UserGroupDao
from bisheng.database.models.user_role import UserRole
from bisheng.role.application.effective_roles import load_effective_roles, load_effective_roles_sync
from bisheng.user.application.policy_bindings import grant_policy_bindings, replace_policy_bindings
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRoleCreate
from bisheng.user.domain.services.auth import LoginUser
from bisheng.user.domain.services.user import UserService
from test.fixtures.managed_tenant import managed_db as managed_db
from test.permission.test_f048_permission_service import _service, _target
from test.role.test_effective_roles import policy_db as policy_db
from test.user.test_mount_role_preservation import binding_snapshot
from test.user.test_mount_role_preservation import mount_db as mount_db


@pytest.fixture
async def upgraded(mount_db, monkeypatch):
    from bisheng.approval.domain.services.user_menu_access_service import UserMenuAccessService
    from bisheng.tenant.domain.services.tenant_service import TenantService

    monkeypatch.setattr(DepartmentDao, "aget_user_admin_departments", AsyncMock(return_value=[]))
    monkeypatch.setattr(UserGroupDao, "aget_user_admin_group", AsyncMock(return_value=[]))
    monkeypatch.setattr(UserMenuAccessService, "list_effective_menu_grants", AsyncMock(return_value=[]))
    monkeypatch.setattr(TenantService, "_is_tenant_admin", AsyncMock(return_value=False))
    monkeypatch.setattr("bisheng.permission.application.is_tenant_admin", AsyncMock(return_value=False))
    monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", AsyncMock(return_value=False))
    with bypass_tenant_filter():
        async with mount_db.sessions() as session:
            (await session.get(UserTenant, 1)).tenant_id = 2
            (await session.get(Role, 2)).quota_config = {"workflow": 7}
            private = await session.get(Role, 9)
            private.department_id = 10  # Root ancestor; not a new grant candidate in child 2.
            private.quota_config = {"workflow": 12}
            session.add_all(
                [
                    Role(id=11, role_name="never assigned", role_type="tenant", tenant_id=3),
                    RoleAccess(id=20, role_id=9, type=99, third_id="admin", tenant_id=1),
                    RoleAccess(id=21, role_id=9, type=99, third_id="build", tenant_id=1),
                    RoleAccess(id=22, role_id=11, type=99, third_id="unassigned-menu", tenant_id=3),
                ]
            )
            await session.commit()
    return mount_db


async def test_upgraded_root_bindings_keep_login_menu_and_sync_consumers(upgraded):
    from bisheng.approval.domain.services.approval_gate import _get_user_role_labels
    from bisheng.dsh.domain.repositories.subject_policy import DshSubjectPolicyRepository

    before = await binding_snapshot(upgraded)
    with tenant_execution_scope(2):
        identity = await LoginUser.init_login_user(77, "policy", tenant_id=2, role_ids=[1, 11])
        assert identity.user_role == [2, 9] and not identity.is_admin()
        assert await UserService._reject_login_if_user_has_no_usable_access(SimpleNamespace(user_id=77)) is None
        assert await LoginUser.user_entry_payload_for_read(SimpleNamespace(user_id=77)) == {
            "has_workbench": False,
            "has_admin_console": True,
            "default_entry": "platform",
        }
        roles, menu = await LoginUser.get_roles_web_menu(SimpleNamespace(user_id=77))
        assert roles == [2, 9] and {"admin", "build", "tool"}.issubset(menu)
        assert "unassigned-menu" not in menu
        assert await _get_user_role_labels(77, 2) == {"regular_user", "role_2", "role_9"}
        with upgraded.sync_sessions() as session:
            sync_policy = load_effective_roles_sync(77, expected_home_tenant_id=2, session=session)
            assert sync_policy.role_ids == (2, 9)
            assert DshSubjectPolicyRepository(session)._role_ids(77) == {2, 9}
            assert DshSubjectPolicyRepository(session)._department_ancestor_ids(77, []) == {20, 30}
    assert await binding_snapshot(upgraded) == before


async def test_original_role_quota_still_obeys_current_tenant_budget(upgraded, monkeypatch):
    from bisheng.common.errcode.tenant_quota import QuotaResponsibilityChangedError
    from bisheng.role.domain.services.quota_service import QuotaService

    with bypass_tenant_filter():
        async with upgraded.sessions() as session:
            (await session.get(Tenant, 2)).quota_config = {"workflow": 9}
            await session.commit()
    count = AsyncMock(return_value=2)
    monkeypatch.setattr(QuotaService, "get_tenant_resource_count", count)
    assert QuotaService._compute_role_quotas((await load_effective_roles(77)).roles)["workflow"] == 12
    assert await QuotaService.get_effective_quota(77, "workflow", 2) == 7
    count.assert_awaited_once_with(2, "workflow")
    with pytest.raises(QuotaResponsibilityChangedError):
        await QuotaService.get_effective_quota(77, "workflow", 3)


async def test_original_roles_do_not_expose_other_tenant_resources_or_override_grants(upgraded):
    from bisheng.permission.domain.services.permission_service import PermissionActor

    await upgraded.create(Flow)
    with bypass_tenant_filter():
        async with upgraded.sessions() as session:
            session.add_all(
                [
                    Flow(id="root-flow", name="Root", tenant_id=1, user_id=77),
                    Flow(id="own-flow", name="Home", tenant_id=2, user_id=77),
                    Flow(id="foreign-flow", name="Other", tenant_id=3, user_id=77),
                    RoleAccess(id=23, role_id=9, type=AccessType.WORKFLOW.value, third_id="own-flow", tenant_id=1),
                ]
            )
            await session.commit()
    assert (await load_effective_roles(77)).role_ids == (2, 9)
    with tenant_execution_scope(2), strict_tenant_filter():
        async with upgraded.sessions() as session:
            assert [row.id for row in (await session.exec(select(Flow))).all()] == ["own-flow"]
            assert (await session.exec(select(Flow).where(Flow.id == "root-flow"))).first() is None
            assert (await session.exec(select(Flow).where(Flow.id == "foreign-flow"))).first() is None
    service, _, _, _, fga, _, events = _service()
    actor = PermissionActor(user_id=77, current_tenant_id=2)
    for tenant_id in (1, 3):
        assert not await service.check_action(actor, _target(tenant_id=tenant_id), "edit")
        assert events.rows[-1][1]["reason"] == "TENANT_MISMATCH"
    assert fga.checks == []
    assert not await service.check_action(actor, _target(tenant_id=2), "edit")
    fga.allowed = True
    assert await service.check_action(actor, _target(tenant_id=2), "edit")
    assert not await service.check_action(actor, _target(tenant_id=3), "edit")


async def test_retain_original_grant_does_not_rebind_or_duplicate_it(upgraded):
    before = await binding_snapshot(upgraded)
    await replace_policy_bindings(77, 2, {2, 9}, {2, 9})
    await grant_policy_bindings(77, 2, {2})
    assert await binding_snapshot(upgraded) == before
    with pytest.raises(RolePolicyUnavailableError):
        await grant_policy_bindings(77, 2, {11})


async def test_saving_original_role_definition_does_not_delete_child_member_bindings(upgraded, monkeypatch):
    from bisheng.role.domain.repositories import role_definition_repository
    from bisheng.role.domain.services.quota_service import QuotaService

    monkeypatch.setattr(role_definition_repository, "get_async_db_session", upgraded.sessions)
    before = await binding_snapshot(upgraded)
    with bypass_tenant_filter():
        async with upgraded.sessions() as session:
            session.add_all(
                [
                    RoleAccess(id=30, role_id=9, type=99, third_id="channel", tenant_id=3),
                    RoleAccess(
                        id=31, role_id=9, type=AccessType.WORKFLOW.value, third_id="legacy-resource", tenant_id=3
                    ),
                ]
            )
            await session.commit()
            role = await session.get(Role, 9)
    assert "channel" in (await load_effective_roles(77)).web_menu
    saved = await role_definition_repository.RoleDefinitionRepository.update(
        role, {"quota_config": {"workflow": 20}, "department_id": None}, ["admin", "build"]
    )
    assert saved.id == 9 and saved.tenant_id == 1 and saved.role_type == "tenant"
    assert await binding_snapshot(upgraded) == before
    policy = await load_effective_roles(77)
    assert policy.role_ids == (2, 9) and {"admin", "build"}.issubset(policy.web_menu)
    assert "channel" not in policy.web_menu
    assert QuotaService._compute_role_quotas(policy.roles)["workflow"] == 20
    with bypass_tenant_filter():
        async with upgraded.sessions() as session:
            assert await session.get(RoleAccess, 31) is not None


@pytest.mark.parametrize("tenant_admin", [False, True])
async def test_explicit_reset_can_revoke_all_old_storage_copies(upgraded, monkeypatch, tenant_admin):
    from bisheng.role.domain.services.role_service import RoleService
    from bisheng.user.api import user as endpoint

    with bypass_tenant_filter():
        async with upgraded.sessions() as session:
            session.add_all(
                [
                    UserRole(id=22, user_id=77, role_id=9, tenant_id=3),
                    UserRole(id=23, user_id=77, role_id=2, tenant_id=2),
                ]
            )
            await session.commit()
    monkeypatch.setattr(endpoint, "update_user_role_hook", Mock())
    sync = AsyncMock()
    monkeypatch.setattr(endpoint.LegacyRBACSyncService, "sync_user_role_change", sync)
    if tenant_admin:
        monkeypatch.setattr(endpoint.UserGroupDao, "get_user_admin_group", Mock(return_value=[]))
        monkeypatch.setattr("bisheng.permission.application.is_tenant_admin", AsyncMock(return_value=True))
        monkeypatch.setattr(RoleService, "list_roles", AsyncMock(return_value={"data": []}))
    result = await endpoint.user_addrole(
        request=None,
        user_role=UserRoleCreate(user_id=77, role_id=[]),
        login_user=SimpleNamespace(user_id=90, tenant_id=2, is_admin=lambda: not tenant_admin),
    )
    assert result.status_code == 200 and await binding_snapshot(upgraded) == []
    sync.assert_awaited_once_with(77, [2, 9], [])
    assert (await load_effective_roles(77)).role_ids == ()


@pytest.mark.parametrize("home_before_login", [1, 2])
@pytest.mark.parametrize("explicit_secondary", [False, True])
@pytest.mark.parametrize("full_department_override", [False, True])
async def test_repeated_sso_snapshot_keeps_original_grants_and_does_not_seed_defaults(
    upgraded, monkeypatch, home_before_login, explicit_secondary, full_department_override
):
    from bisheng.sso_sync.domain.schemas.payloads import LoginSyncRequest, UserAttrsDTO
    from bisheng.sso_sync.domain.services import login_sync_service as module
    from bisheng.user.application import policy_bindings

    with bypass_tenant_filter():
        async with upgraded.sessions() as session:
            (await session.get(UserTenant, 1)).tenant_id = home_before_login
            if full_department_override:
                await session.delete(await session.get(UserDepartment, 2))
            await session.commit()
            user = await session.get(User, 77)
            department = await session.get(Department, 30)
    monkeypatch.setattr(
        module.DeptUpsertService, "assert_parent_chain_exists", AsyncMock(return_value={"leaf": department})
    )
    monkeypatch.setattr(module.TenantMappingHandler, "process", AsyncMock())
    monkeypatch.setattr(
        module.LoginSyncService, "_upsert_user", AsyncMock(return_value=(user, full_department_override))
    )
    for name in (
        "_replace_departments_full",
        "_ensure_primary",
        "_ensure_secondaries",
        "_sync_department_admin_tuples",
        "_reconcile_guest_membership",
    ):
        monkeypatch.setattr(module.LoginSyncService, name, AsyncMock())
    monkeypatch.setattr(module, "AuthJwt", Mock(return_value=SimpleNamespace()))
    monkeypatch.setattr(LoginUser, "create_access_token", Mock(return_value="fixture-token"))
    cleanup = AsyncMock(wraps=policy_bindings.retire_current_policy_bindings)
    defaults = AsyncMock(wraps=policy_bindings.seed_policy_defaults)
    monkeypatch.setattr(policy_bindings, "retire_current_policy_bindings", cleanup)
    monkeypatch.setattr(policy_bindings, "seed_policy_defaults", defaults)
    before = await binding_snapshot(upgraded)
    payload_args = {"secondary_dept_external_ids": []} if explicit_secondary else {}
    payload = LoginSyncRequest(
        external_user_id="policy", primary_dept_external_id="leaf", user_attrs=UserAttrsDTO(), ts=1, **payload_args
    )
    for _ in range(2):
        response = await module.LoginSyncService._execute_locked(payload, "", "sso")
        assert response.user_id == 77 and response.leaf_tenant_id == 2
    cleanup.assert_not_awaited()
    assert all(call.args == (77, set()) for call in defaults.await_args_list)
    assert await binding_snapshot(upgraded) == before
    assert (await load_effective_roles(77)).role_ids == (2, 9)
    # A later explicit revocation cannot be undone by replaying that snapshot,
    # even though the department still has configured default roles.
    from bisheng.common.errcode.user import UserNoRoleForLoginError

    await replace_policy_bindings(77, 2, {2, 9}, set())
    with pytest.raises(UserNoRoleForLoginError):
        await module.LoginSyncService._execute_locked(payload, "", "sso")
    assert await binding_snapshot(upgraded) == []
