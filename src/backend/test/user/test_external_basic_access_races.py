"""覆盖 AC: AC-08, AC-09, AC-10, AC-11。只验证持久裁决, 不证明生产行锁。"""

from dataclasses import replace

import pytest
from sqlmodel import select

from bisheng.common.errcode.sso_sync import KunlianBindingConflictError, KunlianIdentityUnavailableError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.user.domain.models.user_role import UserRole
from test.fixtures import kunlian_onboarding
from test.user.test_external_basic_access import setup_access

onboarding_store = kunlian_onboarding.onboarding_store


async def test_revoke_before_late_apply_wins_across_application_instances(onboarding_store):
    app, command, _ = await setup_access(onboarding_store)
    op = await app.reserve_external_basic_access(command)
    other = type(app)(type(app.repository)(onboarding_store.sessions, role_port=app.repository.role_port))
    await other.set_external_basic_access("fixture", command.identity_key, 7, expected_revision=1, enabled=False)
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.ensure_external_basic_access(command, operation=op)
    with pytest.raises(KunlianBindingConflictError):
        await app.set_external_basic_access("fixture", command.identity_key, 7, expected_revision=1, enabled=False)
    with tenant_execution_scope(7):
        async with onboarding_store.sessions() as session:
            assert {r.role_id for r in (await session.exec(select(UserRole))).all()} == {90}


async def test_apply_then_revoke_removes_only_automatic_relationship(onboarding_store):
    app, command, _ = await setup_access(onboarding_store)
    op = await app.reserve_external_basic_access(command)
    await app.ensure_external_basic_access(command, operation=op)
    await app.set_external_basic_access("fixture", command.identity_key, 7, expected_revision=1, enabled=False)
    current = await app.read_external_basic_access("fixture", command.identity_key, 7)
    assert not current.effective and current.local_blocked
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.reserve_external_basic_access(command)


async def test_template_pause_between_reserve_and_apply_cannot_grant(onboarding_store):
    app, command, roles = await setup_access(onboarding_store)
    op = await app.reserve_external_basic_access(command)
    with tenant_execution_scope(7):
        await roles.set_external_basic_role("fixture", 7, expected_revision=1, enabled=False)
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.ensure_external_basic_access(command, operation=op)


async def test_new_user_projection_fence_rejects_reserved_old_qualification(onboarding_store):
    from bisheng.user.application.external_identity import (
        ExternalShadowIdentity,
        KunlianExternalIdentityApplication,
        UserExternalIdentityProjectionRepository,
    )

    app, command, _ = await setup_access(onboarding_store)
    old = await app.reserve_external_basic_access(command)
    users = KunlianExternalIdentityApplication(UserExternalIdentityProjectionRepository(onboarding_store.sessions))
    identity = ExternalShadowIdentity("https://idp.fixture", "subject", "A", "member", "新的显示名称", True)
    newer = await users.reserve_external_shadow(identity, "b" * 64)
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.ensure_external_basic_access(command, operation=old)
    await users.ensure_external_shadow(identity, "b" * 64, operation=newer)
    with pytest.raises(KunlianBindingConflictError):
        await app.ensure_external_basic_access(command, operation=old)


async def test_template_restore_does_not_clear_a_member_block(onboarding_store):
    app, command, roles = await setup_access(onboarding_store)
    op = await app.reserve_external_basic_access(command)
    await app.ensure_external_basic_access(command, operation=op)
    await app.set_external_basic_access("fixture", command.identity_key, 7, expected_revision=1, enabled=False)
    with tenant_execution_scope(7):
        await roles.set_external_basic_role("fixture", 7, expected_revision=1, enabled=False)
        await roles.set_external_basic_role("fixture", 7, expected_revision=2, enabled=True)
        template = await roles.ensure_external_basic_role(await roles.reserve_external_basic_role("fixture", 7))
    current = replace(command, template=template)
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.reserve_external_basic_access(current)
    await app.set_external_basic_access("fixture", command.identity_key, 7, expected_revision=2, enabled=True)
    assert (
        await app.ensure_external_basic_access(current, operation=await app.reserve_external_basic_access(current))
    ).effective
