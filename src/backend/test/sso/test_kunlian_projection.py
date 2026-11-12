"""T029 覆盖 AC-03, AC-09, AC-17, AC-18, AC-20, AC-22, AC-23, AC-24, AC-26。

独立 SQLite 存储只验证 Owner 提交和恢复合同。不证明生产跨实例行锁。
"""

from contextlib import asynccontextmanager
from importlib import import_module
from unittest.mock import AsyncMock

import pytest
from sqlmodel import SQLModel, select

from bisheng.common.errcode.sso_sync import (
    KunlianBindingConflictError,
    KunlianDependencyUnavailableError,
    KunlianSyncConflictError,
)
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.sso_sync.domain.models.kunlian import KunlianConnectionState, KunlianIdentityBinding, KunlianTenantBinding
from bisheng.tenant.application.external_membership import (
    ExternalMembershipRepository,
    KunlianExternalMembershipApplication,
)
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole
from test.sso import test_kunlian_directory as directory_tests
from test.user import test_kunlian_external_identity as user_tests

owner = user_tests.owner
directory_store = directory_tests.directory_store


def member(mid="member-1", subject="subject-1", *, name="当前名称", status="ACTIVE"):
    value = directory_tests.member(mid, subject, status=status)
    value["summary"] = {"display_name": name, "roles": [{"id": "external-role", "status": "ACTIVE"}]}
    return value


@pytest.fixture
async def projection(owner, directory_store):
    user_app, users, user_module = owner
    repo, controls, _, _ = directory_store
    async with users() as session:
        connection = await session.connection()
        await connection.run_sync(
            lambda sync: SQLModel.metadata.create_all(sync, tables=[Tenant.__table__, UserTenant.__table__])
        )
        session.add(Tenant(id=7, tenant_code="seven", tenant_name="Seven"))
        session.add(Tenant(id=8, tenant_code="eight", tenant_name="Eight"))
        await session.commit()
    projector = AsyncMock()
    tenant_app = KunlianExternalMembershipApplication(
        ExternalMembershipRepository(users), project_membership=projector, ensure_department_membership=AsyncMock()
    )
    await repo.bind_tenant("fixture", "external-a", verified_local_tenant_id=7, expected_revision=None)
    await directory_tests.publish(repo, members=[member()])
    key = repo.identity_key(directory_tests.ISSUER, "external-a", "subject-1")
    try:
        module = import_module("bisheng.sso_sync.domain.services.kunlian_projection")
    except ModuleNotFoundError as exc:
        if exc.name != "bisheng.sso_sync.domain.services.kunlian_projection":
            raise
        pytest.fail("T030 projection coordinator is not implemented", pytrace=False)

    def service():
        return module.KunlianProjectionService(repo, user_owner=user_app, tenant_owner=tenant_app)

    return service, repo, user_app, users, controls, projector, key, user_module


async def test_partial_owner_commit_recovers_same_user_and_frozen_target(projection):
    service, repo, _, users, controls, projector, key, _ = projection
    projector.side_effect = KunlianDependencyUnavailableError()
    with pytest.raises(KunlianDependencyUnavailableError):
        await service().project_identity(key)
    async with users() as session:
        rows = (await session.exec(select(User))).all()
        assert len(rows) == 1 and rows[0].source == "kunlian"
        uid = rows[0].user_id
        assert not (await session.exec(select(UserRole))).all()
        assert not (await session.exec(select(UserTenant))).all()
    async with controls() as session:
        binding = await session.get(KunlianIdentityBinding, key)
        mapping = await session.get(KunlianTenantBinding, ("fixture", "external-a"))
        assert binding.projection_status == "FAILED" and binding.local_user_id is None
        assert mapping.materialized is True
        assert (await session.get(KunlianConnectionState, "fixture")).active_batch_id is not None
    with pytest.raises(KunlianBindingConflictError):
        await repo.bind_tenant("fixture", "external-a", verified_local_tenant_id=8, expected_revision=1)
    projector.side_effect = None
    assert await service().project_identity(key) == uid
    assert await service().project_identity(key) == uid
    async with users() as session:
        assert len((await session.exec(select(User))).all()) == 1
        assert len((await session.exec(select(UserTenant))).all()) == 1
        assert not (await session.exec(select(UserRole))).all()
    async with controls() as session:
        row = await session.get(KunlianIdentityBinding, key)
        assert row.projection_status == "SUCCEEDED" and row.projected_revision == row.source_revision


@pytest.mark.parametrize("loss", ["revision", "transaction"])
async def test_reserved_owner_operation_is_not_dispatched_after_original_scope_lost(projection, monkeypatch, loss):
    service, repo, user_app, users, controls, _, key, _ = projection
    opened = []

    @asynccontextmanager
    async def capturing_sessions():
        async with controls() as session:
            opened.append(session)
            yield session

    repo.session_factory = capturing_sessions
    reserve = user_app.reserve_external_shadow

    async def lose_scope(*args):
        operation = await reserve(*args)
        if loss == "transaction":
            await opened[-1].rollback()
        else:
            async with controls() as session:
                binding = await session.get(KunlianIdentityBinding, key)
                binding.source_revision = "b" * 64
                session.add(binding)
                await session.commit()
        return operation

    monkeypatch.setattr(user_app, "reserve_external_shadow", lose_scope)
    apply = AsyncMock(wraps=user_app.ensure_external_shadow)
    monkeypatch.setattr(user_app, "ensure_external_shadow", apply)
    with pytest.raises(KunlianSyncConflictError):
        await service().project_identity(key)
    apply.assert_not_awaited()
    async with users() as session:
        assert not (await session.exec(select(User))).all()
    async with controls() as session:
        row = await session.get(KunlianIdentityBinding, key)
        assert row.projected_revision is None
        if loss == "revision":
            assert row.source_revision == "b" * 64 and row.projection_status == "PENDING"


async def test_one_failed_identity_does_not_block_completed_identities(projection, monkeypatch):
    service, repo, user_app, _, controls, _, key, _ = projection
    await directory_tests.publish(repo, members=[member(), member("member-2", "subject-2")])
    ensure = user_app.ensure_external_shadow

    async def selective_failure(identity, *args, **kwargs):
        if identity.subject == "subject-1":
            raise KunlianDependencyUnavailableError()
        return await ensure(identity, *args, **kwargs)

    monkeypatch.setattr(user_app, "ensure_external_shadow", selective_failure)
    outcome = await service().project_pending("fixture")
    assert outcome["succeeded"] == 1 and outcome["failed"] == 1
    async with controls() as session:
        assert (await session.get(KunlianIdentityBinding, key)).projection_status == "FAILED"
        other = await session.get(
            KunlianIdentityBinding, repo.identity_key(directory_tests.ISSUER, "external-a", "subject-2")
        )
        assert other.projection_status == "SUCCEEDED"


async def test_manual_disable_during_projection_rejects_old_receipt_and_preserves_role(projection, monkeypatch):
    from bisheng.sso_sync.application.kunlian import KunlianManualAccountApplication

    service, repo, user_app, users, controls, _, key, _ = projection
    uid = await service().project_identity(key)
    async with users() as session:
        session.add(UserRole(user_id=uid, role_id=910))
        await session.commit()
    await directory_tests.publish(repo, members=[member(name="新目录名称")])
    ensure = user_app.ensure_external_shadow

    async def manual_after_user_commit(*args, **kwargs):
        result = await ensure(*args, **kwargs)
        await KunlianManualAccountApplication(repo).set_account_status(uid, disabled=True, user_owner=user_app)
        return result

    monkeypatch.setattr(user_app, "ensure_external_shadow", manual_after_user_commit)
    with pytest.raises((KunlianBindingConflictError, KunlianSyncConflictError)):
        await service().project_identity(key)
    async with controls() as session:
        row = await session.get(KunlianIdentityBinding, key)
        assert row.local_override is True and row.projected_revision != row.source_revision
    async with users() as session:
        user = await session.get(User, uid)
        assert user.delete == 1 and user.disable_source == "manual"
        assert len((await session.exec(select(UserRole))).all()) == 1
    monkeypatch.setattr(user_app, "ensure_external_shadow", ensure)
    assert await service().project_identity(key) == uid
    async with users() as session:
        assert (await session.get(User, uid)).delete == 1


@pytest.mark.parametrize("unavailable", ["DISABLED", "missing"])
async def test_disabled_or_missing_member_projects_stop_and_restores_without_grant_deletion(projection, unavailable):
    service, repo, _, users, controls, _, key, _ = projection
    uid = await service().project_identity(key)
    async with users() as session:
        session.add(UserRole(user_id=uid, role_id=910))
        await session.commit()
    async with controls() as session:
        initial_epoch = (await session.get(KunlianIdentityBinding, key)).auth_epoch
    await directory_tests.publish(repo, members=[] if unavailable == "missing" else [member(status=unavailable)])
    assert await service().project_identity(key) == uid
    async with users() as session:
        stopped = await session.get(User, uid)
        assert stopped.delete == 1 and stopped.disable_source == "kunlian" and stopped.user_name == "当前名称"
        assert len((await session.exec(select(UserRole))).all()) == 1
    async with controls() as session:
        stopped_epoch = (await session.get(KunlianIdentityBinding, key)).auth_epoch
        assert stopped_epoch > initial_epoch
    await directory_tests.publish(repo, members=[member(name="恢复名称")])
    assert await service().project_identity(key) == uid
    async with users() as session:
        restored = await session.get(User, uid)
        assert restored.delete == 0 and restored.disable_source is None and restored.user_name == "恢复名称"
        assert len((await session.exec(select(UserRole))).all()) == 1
    async with controls() as session:
        assert (await session.get(KunlianIdentityBinding, key)).auth_epoch == stopped_epoch
