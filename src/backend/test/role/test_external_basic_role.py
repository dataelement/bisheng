"""覆盖 AC: AC-03, AC-04, AC-09, AC-10, AC-11。"""

from importlib import import_module

import pytest
from sqlmodel import select

from bisheng.common.errcode.sso_sync import KunlianBindingConflictError, KunlianIdentityUnavailableError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.role import Role
from bisheng.database.models.role_access import RoleAccess
from bisheng.database.models.tenant import Tenant
from bisheng.role.domain.models.external_basic_role import RoleExternalBasicRole
from test.fixtures import kunlian_onboarding

onboarding_store = kunlian_onboarding.onboarding_store


async def setup_role(store):
    module = import_module("bisheng.role.application.external_basic_role")
    async with store.sessions() as session:
        session.add(Tenant(id=7, tenant_code="seven", tenant_name="A", parent_tenant_id=1))
        await session.commit()
    return module, module.ExternalBasicRoleApplication(module.RoleExternalBasicRoleRepository(store.sessions))


async def test_fixed_template_singleton_no_resource_grants_or_name_claim(onboarding_store):
    _, app = await setup_role(onboarding_store)
    with tenant_execution_scope(7):
        operation = await app.reserve_external_basic_role("fixture", 7)
        role = await app.ensure_external_basic_role(operation)
        assert role.role_id not in (1, 2) and role.state == "APPLIED"
        assert await app.ensure_external_basic_role(operation) == role
        async with onboarding_store.sessions() as session:
            values = (await session.exec(select(RoleAccess).where(RoleAccess.role_id == role.role_id))).all()
            assert {(x.type, x.third_id, x.tenant_id) for x in values} == {
                (99, key, 7) for key in ("admin", "build", "create_workflow")
            }
            assert (await session.exec(select(Role).where(Role.id == role.role_id))).one().role_type == "tenant"
        other = await app.reserve_external_basic_role("other", 7)
        assert (await app.ensure_external_basic_role(other)).role_id != role.role_id


async def test_pause_durable_clear_menus_and_explicit_restore_invalidates_old_operation(onboarding_store):
    _, app = await setup_role(onboarding_store)
    with tenant_execution_scope(7):
        op = await app.reserve_external_basic_role("fixture", 7)
        role = await app.ensure_external_basic_role(op)
        assert await app.set_external_basic_role("fixture", 7, expected_revision=1, enabled=False) == 2
        async with onboarding_store.sessions() as session:
            assert not (await session.exec(select(RoleAccess).where(RoleAccess.role_id == role.role_id))).all()
        with pytest.raises(KunlianIdentityUnavailableError):
            await app.reserve_external_basic_role("fixture", 7)
        with pytest.raises(KunlianBindingConflictError):
            await app.set_external_basic_role("fixture", 7, expected_revision=1, enabled=False)
        await app.set_external_basic_role("fixture", 7, expected_revision=2, enabled=True)
        with pytest.raises(KunlianBindingConflictError):
            await app.ensure_external_basic_role(op)
        new = await app.reserve_external_basic_role("fixture", 7)
        restored = await app.ensure_external_basic_role(new)
        assert restored.role_id == role.role_id and restored.template_revision > role.template_revision


async def test_missing_or_out_of_template_role_is_suspended_without_auto_repair(onboarding_store):
    _, app = await setup_role(onboarding_store)
    with tenant_execution_scope(7):
        op = await app.reserve_external_basic_role("fixture", 7)
        role = await app.ensure_external_basic_role(op)
        async with onboarding_store.sessions() as session:
            session.add(RoleAccess(role_id=role.role_id, third_id="create_app", type=99, tenant_id=7))
            await session.commit()
        with pytest.raises(KunlianIdentityUnavailableError):
            await app.reserve_external_basic_role("fixture", 7)
        async with onboarding_store.sessions() as session:
            state = (await session.exec(select(RoleExternalBasicRole))).one()
            assert state.state == "SUSPENDED"
        with pytest.raises(KunlianIdentityUnavailableError):
            await app.ensure_external_basic_role(op)


async def test_template_name_collision_never_claims_the_human_role(onboarding_store):
    from hashlib import sha256

    _, app = await setup_role(onboarding_store)
    with tenant_execution_scope(7):
        async with onboarding_store.sessions() as session:
            session.add(Role(id=90, role_name="昆联工作流基础_" + sha256(b"fixture").hexdigest()[:12], tenant_id=7))
            await session.commit()
        op = await app.reserve_external_basic_role("fixture", 7)
        with pytest.raises(KunlianBindingConflictError):
            await app.ensure_external_basic_role(op)
        async with onboarding_store.sessions() as session:
            assert not (await session.exec(select(RoleAccess))).all()
            assert (await session.exec(select(RoleExternalBasicRole))).one().role_id is None
