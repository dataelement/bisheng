"""T023 覆盖 AC-03, AC-04, AC-17, AC-20, AC-23。显式成员关系与来源隔离。"""

from importlib import import_module
from unittest.mock import AsyncMock

import pytest
from sqlmodel import SQLModel, select

from bisheng.common.errcode.sso_sync import KunlianBindingConflictError, KunlianIdentityUnavailableError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.sso_sync.domain.schemas.kunlian import KunlianTenantMapping
from test.user import test_kunlian_external_identity as user_tests

owner = user_tests.owner


@pytest.fixture
async def membership(owner):
    user_app, sessions, module = owner
    uid, _ = await user_tests.project(user_app, user_tests.identity(module), "a" * 64)
    async with sessions() as session:
        connection = await session.connection()
        await connection.run_sync(
            lambda sync: SQLModel.metadata.create_all(sync, tables=[Tenant.__table__, UserTenant.__table__])
        )
        session.add(Tenant(id=1, tenant_code="root", tenant_name="Root"))
        session.add(Tenant(id=7, tenant_code="seven", tenant_name="Seven"))
        session.add(Tenant(id=8, tenant_code="eight", tenant_name="Eight"))
        await session.commit()
    try:
        app_module = import_module("bisheng.tenant.application.external_membership")
    except ModuleNotFoundError as exc:
        if exc.name not in ("bisheng.tenant.application", "bisheng.tenant.application.external_membership"):
            raise
        pytest.fail("T024 external membership application is not implemented", pytrace=False)
    projector = AsyncMock()
    app = app_module.KunlianExternalMembershipApplication(
        app_module.ExternalMembershipRepository(sessions),
        project_membership=projector,
    )
    return app, sessions, projector, uid


def mapping(tid=7):
    return KunlianTenantMapping(connection_id="fixture", external_tenant_id="tenant-1", local_tenant_id=tid, revision=1)


async def test_membership_is_idempotent_and_never_relocates(membership):
    app, sessions, project, uid = membership
    with tenant_execution_scope(7):
        await app.ensure_external_membership(uid, mapping())
        await app.ensure_external_membership(uid, mapping())
    async with sessions() as session:
        rows = (await session.exec(select(UserTenant).where(UserTenant.user_id == uid))).all()
        assert [(r.tenant_id, r.status, r.is_active) for r in rows] == [(7, "active", 1)]
    with tenant_execution_scope(8), pytest.raises(KunlianBindingConflictError):
        await app.ensure_external_membership(uid, mapping(8))
    assert project.await_count == 2


@pytest.mark.parametrize("case", ["missing", "disabled", "wrong_scope", "local_account"])
async def test_invalid_membership_never_falls_back_or_creates_tenant(membership, case):
    from bisheng.user.domain.models.user import User

    app, sessions, project, uid = membership
    tid, context = 7, 7
    if case == "missing":
        tid = context = 99
    elif case == "disabled":
        async with sessions() as session:
            tenant = await session.get(Tenant, 7)
            tenant.status = "disabled"
            session.add(tenant)
            await session.commit()
    elif case == "wrong_scope":
        context = 8
    else:
        async with sessions() as session:
            local = User(user_name="local", source="local", password="")
            session.add(local)
            await session.commit()
            uid = local.user_id
    with tenant_execution_scope(context), pytest.raises((KunlianBindingConflictError, KunlianIdentityUnavailableError)):
        await app.ensure_external_membership(uid, mapping(tid))
    project.assert_not_awaited()
    async with sessions() as session:
        assert not (await session.exec(select(UserTenant))).all()
        assert await session.get(Tenant, 99) is None


async def test_permission_failure_does_not_publish_membership(membership):
    app, sessions, projector, uid = membership
    projector.side_effect = KunlianIdentityUnavailableError()
    with tenant_execution_scope(7), pytest.raises(KunlianIdentityUnavailableError):
        await app.ensure_external_membership(uid, mapping())
    async with sessions() as session:
        assert not (await session.exec(select(UserTenant))).all()
    projector.side_effect = None
    with tenant_execution_scope(7):
        await app.ensure_external_membership(uid, mapping())


async def test_queued_permission_write_is_not_complete_until_current_relation_verified(membership, monkeypatch):
    from types import SimpleNamespace

    from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError
    from bisheng.tenant.application import external_membership as module

    app, sessions, _, uid = membership
    api = SimpleNamespace(apply_changes=AsyncMock(), check=AsyncMock(return_value=False))
    monkeypatch.setattr(module, "get_permission_relation_api", AsyncMock(return_value=api))
    app.project_membership = module.project_tenant_membership
    with tenant_execution_scope(7), pytest.raises(KunlianDependencyUnavailableError):
        await app.ensure_external_membership(uid, mapping())
    async with sessions() as session:
        assert not (await session.exec(select(UserTenant))).all()
    api.check.return_value = True
    with tenant_execution_scope(7):
        await app.ensure_external_membership(uid, mapping())
    assert api.check.call_args.kwargs["consistency"] == "HIGHER_CONSISTENCY"


async def test_authority_reads_current_mapping_and_keeps_ordinary_users_off_control_tables(membership, monkeypatch):
    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.tenant.application import external_membership as module
    from bisheng.user.domain.models.user import User

    app, sessions, _, uid = membership
    if not hasattr(module, "resolve_external_tenant_if_any"):
        pytest.fail("T026 external tenant authority is not implemented", pytrace=False)
    with tenant_execution_scope(7):
        await app.ensure_external_membership(uid, mapping())
    reader = AsyncMock(return_value=mapping())
    with tenant_execution_scope(11):
        tenant = await module.resolve_external_tenant_if_any(uid, repository=app.repository, mapping_reader=reader)
        assert tenant.id == 7 and get_current_tenant_id() == 11
    reader.side_effect = KunlianIdentityUnavailableError()
    with pytest.raises(KunlianIdentityUnavailableError):
        await module.resolve_external_tenant_if_any(uid, repository=app.repository, mapping_reader=reader)
    async with sessions() as session:
        local = User(user_name="local-only", source="local", password="")
        session.add(local)
        await session.commit()
        local_id = local.user_id
    reader.reset_mock()
    assert (
        await module.resolve_external_tenant_if_any(local_id, repository=app.repository, mapping_reader=reader) is None
    )
    reader.assert_not_awaited()
