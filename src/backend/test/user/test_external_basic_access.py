"""覆盖 AC: AC-02, AC-03, AC-04, AC-08, AC-09, AC-10, AC-11。"""

from dataclasses import replace
from importlib import import_module

import pytest
from sqlalchemy import delete, event
from sqlmodel import select

from bisheng.common.errcode.sso_sync import KunlianBindingConflictError, KunlianIdentityUnavailableError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import UserTenant
from bisheng.user.application.external_identity import (
    ExternalShadowIdentity,
    KunlianExternalIdentityApplication,
    UserExternalIdentityProjectionRepository,
)
from bisheng.user.domain.models.external_basic_access import UserExternalBasicAccess
from bisheng.user.domain.models.user_role import UserRole
from test.fixtures import kunlian_onboarding
from test.role.test_external_basic_role import setup_role

onboarding_store = kunlian_onboarding.onboarding_store


async def setup_access(store):
    _, roles = await setup_role(store)
    module = import_module("bisheng.user.application.external_basic_access")
    identity = ExternalShadowIdentity("https://idp.fixture", "subject", "A", "member", "同名用户", True)
    users = KunlianExternalIdentityApplication(UserExternalIdentityProjectionRepository(store.sessions))
    operation = await users.reserve_external_shadow(identity, "a" * 64)
    uid = await users.ensure_external_shadow(identity, "a" * 64, operation=operation)
    receipt = await users.read_projection_receipt(operation)
    with tenant_execution_scope(7):
        async with store.sessions() as session:
            session.add(UserTenant(user_id=uid, tenant_id=7, is_active=1, status="active"))
            session.add(Role(id=90, role_name="人工角色", tenant_id=7))
            session.add(UserRole(user_id=uid, role_id=90, tenant_id=7))
            await session.commit()
        template = await roles.ensure_external_basic_role(await roles.reserve_external_basic_role("fixture", 7))
    repository = module.UserExternalBasicAccessRepository(store.sessions, role_port=roles)
    app = module.ExternalBasicAccessApplication(repository)
    command = module.BasicAccessCommand("fixture", identity.identity_key, 7, uid, receipt, template)
    return app, command, roles


async def test_adds_only_owned_relation_and_preserves_manual_grants(onboarding_store):
    app, command, _ = await setup_access(onboarding_store)
    op = await app.reserve_external_basic_access(command)
    result = await app.ensure_external_basic_access(command, operation=op)
    assert result.effective and result.state == "APPLIED"
    assert await app.ensure_external_basic_access(command, operation=op) == result
    with tenant_execution_scope(7):
        async with onboarding_store.sessions() as session:
            rows = (await session.exec(select(UserRole).where(UserRole.user_id == command.user_id))).all()
            assert {r.role_id for r in rows} == {90, command.template.role_id}
            assert all(r.tenant_id == 7 for r in rows)


async def test_identity_target_or_stale_projection_is_refused(onboarding_store):
    app, value, _ = await setup_access(onboarding_store)
    for command in (
        replace(value, user_id=value.user_id + 1),
        replace(value, tenant_id=8),
        replace(value, projection=replace(value.projection, fence=0)),
    ):
        with pytest.raises((KunlianBindingConflictError, KunlianIdentityUnavailableError)):
            await app.reserve_external_basic_access(command)


async def test_missing_applied_relation_becomes_durable_block_not_auto_repair(onboarding_store):
    app, command, _ = await setup_access(onboarding_store)
    op = await app.reserve_external_basic_access(command)
    await app.ensure_external_basic_access(command, operation=op)
    with tenant_execution_scope(7):
        async with onboarding_store.sessions() as session:
            await session.exec(
                delete(UserRole).where(
                    UserRole.user_id == command.user_id, UserRole.role_id == command.template.role_id
                )
            )
            await session.commit()
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.reserve_external_basic_access(command)
    with tenant_execution_scope(7):
        async with onboarding_store.sessions() as session:
            row = (await session.exec(select(UserExternalBasicAccess))).one()
            assert row.local_blocked and row.state == "BLOCKED"


async def test_relation_and_receipt_rollback_together(onboarding_store):
    app, command, _ = await setup_access(onboarding_store)
    op = await app.reserve_external_basic_access(command)

    def fail_after_access_update(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE user_external_basic_access"):
            raise RuntimeError("fixture atomic rollback")

    event.listen(onboarding_store.engine.sync_engine, "after_cursor_execute", fail_after_access_update)
    try:
        with pytest.raises(RuntimeError, match="fixture atomic rollback"):
            await app.ensure_external_basic_access(command, operation=op)
    finally:
        event.remove(onboarding_store.engine.sync_engine, "after_cursor_execute", fail_after_access_update)
    with tenant_execution_scope(7):
        async with onboarding_store.sessions() as session:
            assert {r.role_id for r in (await session.exec(select(UserRole))).all()} == {90}
            assert (await session.exec(select(UserExternalBasicAccess))).one().state == "PENDING"
    assert (await app.ensure_external_basic_access(command, operation=op)).effective


async def test_revoking_automatic_access_preserves_independent_qualification(onboarding_store, monkeypatch):
    app, command, _ = await setup_access(onboarding_store)
    op = await app.reserve_external_basic_access(command)
    await app.ensure_external_basic_access(command, operation=op)
    await app.set_external_basic_access("fixture", command.identity_key, 7, expected_revision=1, enabled=False)
    facts = await app.read_current_qualification(
        command.user_id, identity_key=command.identity_key, connection_id="fixture", tenant_id=7
    )
    assert facts.role_ids == (90,)


async def test_owner_chain_provisions_real_child_user_template_and_single_relation(onboarding_store):
    from unittest.mock import AsyncMock

    from bisheng.role.application.external_basic_role import (
        ExternalBasicRoleApplication,
        RoleExternalBasicRoleRepository,
    )
    from bisheng.sso_sync.domain.schemas.kunlian import KunlianTenantMapping
    from bisheng.tenant.application.external_membership import (
        ExternalMembershipRepository,
        KunlianExternalMembershipApplication,
    )
    from bisheng.tenant.application.external_provision import (
        ExternalTenantCommand,
        KunlianExternalTenantApplication,
        TenantExternalProvisionRepository,
    )
    from bisheng.user.application.external_basic_access import (
        BasicAccessCommand,
        ExternalBasicAccessApplication,
        UserExternalBasicAccessRepository,
    )

    tenants = KunlianExternalTenantApplication(TenantExternalProvisionRepository(onboarding_store.sessions))
    source = ExternalTenantCommand("fixture", "https://idp.fixture", "A", "新租户", "batch", "a" * 64, 1)
    tenant_op = await tenants.reserve_external_tenant(source)
    tenant = await tenants.ensure_external_tenant(source, operation=tenant_op)
    identity = ExternalShadowIdentity("https://idp.fixture", "subject", "A", "member", "用户", True)
    users = KunlianExternalIdentityApplication(UserExternalIdentityProjectionRepository(onboarding_store.sessions))
    user_op = await users.reserve_external_shadow(identity, "a" * 64)
    uid = await users.ensure_external_shadow(identity, "a" * 64, operation=user_op)
    user_receipt = await users.read_projection_receipt(user_op)
    projector = AsyncMock()
    membership = KunlianExternalMembershipApplication(
        ExternalMembershipRepository(onboarding_store.sessions), project_membership=projector
    )
    mapping = KunlianTenantMapping(
        connection_id="fixture", external_tenant_id="A", local_tenant_id=tenant.local_tenant_id, revision=1
    )
    with tenant_execution_scope(tenant.local_tenant_id):
        await membership.ensure_external_membership(uid, mapping)
    projector.assert_awaited_once_with(uid, tenant.local_tenant_id)
    roles = ExternalBasicRoleApplication(RoleExternalBasicRoleRepository(onboarding_store.sessions))
    template = await roles.ensure_external_basic_role(
        await roles.reserve_external_basic_role("fixture", tenant.local_tenant_id)
    )
    access = ExternalBasicAccessApplication(
        UserExternalBasicAccessRepository(onboarding_store.sessions, role_port=roles)
    )
    command = BasicAccessCommand("fixture", identity.identity_key, tenant.local_tenant_id, uid, user_receipt, template)
    operation = await access.reserve_external_basic_access(command)
    assert (await access.ensure_external_basic_access(command, operation=operation)).effective
    assert (await access.ensure_external_basic_access(command, operation=operation)).effective
    with tenant_execution_scope(tenant.local_tenant_id):
        async with onboarding_store.sessions() as session:
            actual = (await session.exec(select(UserRole))).all()
            assert [(r.user_id, r.role_id, r.tenant_id) for r in actual] == [
                (uid, template.role_id, tenant.local_tenant_id)
            ]
