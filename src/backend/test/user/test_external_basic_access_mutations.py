"""覆盖 AC: AC-04, AC-09, AC-13。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request
from sqlalchemy import event
from sqlmodel import select

from bisheng.common.errcode.sso_sync import KunlianBindingConflictError, KunlianIdentityUnavailableError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.user.domain.models.external_basic_access import UserExternalBasicAccess
from bisheng.user.domain.models.user_role import UserRole, UserRoleCreate, UserRoleDao
from test.fixtures import kunlian_onboarding
from test.user.test_external_basic_access import setup_access

onboarding_store = kunlian_onboarding.onboarding_store


async def test_ordinary_role_changes_remain_under_original_authorization(onboarding_store):
    from bisheng.user.domain.repositories.external_basic_access import UserExternalBasicAccessRepository

    actor = SimpleNamespace(user_id=101, tenant_id=1, is_admin=lambda: True)
    repository = UserExternalBasicAccessRepository(onboarding_store.sessions)
    # 没有自动来源的用户继续由原入口决定可绑定角色, 不套用受管用户限制。
    assert await repository.apply_role_mutation(999, add_ids=[1], delete_ids=[], actor=actor) is None


async def test_user_role_endpoint_records_revocation_before_retry(onboarding_store, monkeypatch):
    from bisheng.user.api import user as api
    from bisheng.user.application import external_basic_access as port

    app, command, _ = await setup_access(onboarding_store)
    op = await app.reserve_external_basic_access(command)
    await app.ensure_external_basic_access(command, operation=op)
    monkeypatch.setattr(port, "get_repository", lambda: app.repository)
    monkeypatch.setattr(
        UserRoleDao,
        "get_user_roles",
        lambda _: [SimpleNamespace(role_id=90), SimpleNamespace(role_id=command.template.role_id)],
    )
    unsafe_delete = MagicMock()
    monkeypatch.setattr(UserRoleDao, "delete_user_roles", unsafe_delete)
    monkeypatch.setattr(api, "update_user_role_hook", lambda *a: None)
    monkeypatch.setattr(api.LegacyRBACSyncService, "sync_user_role_change", AsyncMock())
    actor = SimpleNamespace(user_id=101, user_name="管理员", tenant_id=1, is_admin=lambda: True)
    await api.user_addrole(
        request=Request({"type": "http"}),
        user_role=UserRoleCreate(user_id=command.user_id, role_id=[90]),
        login_user=actor,
    )
    unsafe_delete.assert_not_called()
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.ensure_external_basic_access(command, operation=op)
    with tenant_execution_scope(7):
        async with onboarding_store.sessions() as session:
            assert (await session.exec(select(UserExternalBasicAccess))).one().local_blocked
            assert {r.role_id for r in (await session.exec(select(UserRole))).all()} == {90}


async def test_reassignment_refused_and_failed_mutation_keeps_source_and_relation(onboarding_store):
    app, command, _ = await setup_access(onboarding_store)
    op = await app.reserve_external_basic_access(command)
    await app.ensure_external_basic_access(command, operation=op)
    actor = SimpleNamespace(user_id=101, user_name="管理员", tenant_id=1, is_admin=lambda: True)
    with pytest.raises(KunlianBindingConflictError):
        await app.repository.apply_role_mutation(
            command.user_id + 10, add_ids=[command.template.role_id], delete_ids=[], actor=actor
        )

    def fail_userrole_delete(conn, cursor, statement, params, context, executemany):
        if statement.startswith("DELETE FROM userrole"):
            raise RuntimeError("fixture revoke rollback")

    event.listen(onboarding_store.engine.sync_engine, "after_cursor_execute", fail_userrole_delete)
    try:
        with pytest.raises(RuntimeError, match="fixture revoke rollback"):
            await app.repository.apply_role_mutation(
                command.user_id, add_ids=[], delete_ids=[command.template.role_id], actor=actor
            )
    finally:
        event.remove(onboarding_store.engine.sync_engine, "after_cursor_execute", fail_userrole_delete)
    assert (await app.read_external_basic_access("fixture", command.identity_key, 7)).effective
