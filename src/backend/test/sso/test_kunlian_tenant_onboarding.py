"""覆盖 AC: AC-01, AC-02, AC-03, AC-07, AC-10, AC-11, AC-12。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import SQLModel, select

from bisheng.common.errcode.sso_sync import KunlianDirectoryNotReadyError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.tenant import Tenant
from bisheng.role.application.external_basic_role import ExternalBasicRoleApplication, RoleExternalBasicRoleRepository
from bisheng.sso_sync.domain.models.kunlian import KunlianConnectionState, KunlianIdentityBinding, KunlianTenantBinding
from bisheng.sso_sync.domain.repositories.kunlian import KunlianDirectoryRepository
from bisheng.sso_sync.domain.services.kunlian_projection import KunlianProjectionService
from bisheng.tenant.application.external_membership import (
    ExternalMembershipRepository,
    KunlianExternalMembershipApplication,
)
from bisheng.tenant.application.external_provision import (
    KunlianExternalTenantApplication,
    TenantExternalProvisionRepository,
)
from bisheng.user.application.external_basic_access import (
    ExternalBasicAccessApplication,
    UserExternalBasicAccessRepository,
)
from bisheng.user.application.external_identity import (
    KunlianExternalIdentityApplication,
    UserExternalIdentityProjectionRepository,
)
from bisheng.user.domain.models.user_role import UserRole
from test.fixtures import kunlian_onboarding
from test.sso import test_kunlian_directory as directory
from test.sso.test_kunlian_admission import config

onboarding_store = kunlian_onboarding.onboarding_store


@pytest.fixture
async def onboarding(onboarding_store):
    from bisheng.sso_sync.domain.services.kunlian_onboarding import KunlianOnboardingService

    tables = [t for t in SQLModel.metadata.sorted_tables if t.name.startswith("kunlian_")]
    async with onboarding_store.engine.begin() as connection:
        await connection.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=tables))
    async with onboarding_store.sessions() as session:
        session.add(KunlianConnectionState(connection_id="fixture", enabled=True))
        await session.commit()
    sessions = onboarding_store.sessions
    repo = KunlianDirectoryRepository(sessions)
    users = KunlianExternalIdentityApplication(UserExternalIdentityProjectionRepository(sessions))
    tenants = KunlianExternalTenantApplication(TenantExternalProvisionRepository(sessions))
    membership = KunlianExternalMembershipApplication(
        ExternalMembershipRepository(sessions), project_membership=AsyncMock()
    )
    roles = ExternalBasicRoleApplication(RoleExternalBasicRoleRepository(sessions))
    access = ExternalBasicAccessApplication(UserExternalBasicAccessRepository(sessions, role_port=roles))
    projection = KunlianProjectionService(repo, user_owner=users, tenant_owner=membership)
    cfg = config()
    cfg.auto_onboarding_enabled = True
    service = KunlianOnboardingService(
        repo, cfg, tenants=tenants, users=users, roles=roles, access=access, projection=projection
    )
    return SimpleNamespace(
        service=service,
        repo=repo,
        sessions=sessions,
        users=users,
        tenants=tenants,
        roles=roles,
        access=access,
        projection=projection,
        config=cfg,
    )


async def run_round(service):
    stage, cursor = "tenants", ""
    for _ in range(30):
        result = await service.recover("fixture", stage=stage, after_key=cursor, limit=2)
        if not result["has_more"]:
            return
        stage, cursor = result["next_stage"], result["next_after_key"]
    pytest.fail("bounded onboarding did not finish")


async def test_published_directory_opens_distinct_tenants_and_qualifies_existing_users(onboarding):
    s = onboarding
    await directory.publish(
        s.repo,
        tenants=[directory.tenant(), directory.tenant("external-b")],
        members=[directory.member(), directory.member("m2", "s2", "external-b")],
    )
    await run_round(s.service)
    # 新服务实例与下一轮扫描都以持久回执恢复, 不靠内存中的成功集合。
    await run_round(s.service)
    async with s.sessions() as session:
        children = (await session.exec(select(Tenant).where(Tenant.parent_tenant_id == 1))).all()
        bindings = (await session.exec(select(KunlianIdentityBinding))).all()
        mappings = (await session.exec(select(KunlianTenantBinding))).all()
        assert len(children) == len(bindings) == len(mappings) == 2
        assert len({b.local_user_id for b in bindings}) == 2
    for binding in bindings:
        target = next(m.local_tenant_id for m in mappings if m.external_tenant_id == binding.external_tenant_id)
        facts = await s.service.current_qualification(binding)
        with tenant_execution_scope(target):
            async with s.sessions() as session:
                actual = (await session.exec(select(UserRole))).all()
                assert len(actual) == 1 and actual[0].user_id == facts.user_id


async def test_unpublished_or_stale_directory_never_creates_tenant(onboarding):
    s = onboarding
    lease = await s.repo.claim_or_renew_lease("fixture", "worker", key_version="key-v1", page_size=20)
    await s.repo.stage_page(
        lease, tenants=[directory.tenant()], members=[directory.member()], next_cursor_ciphertext=None
    )
    with pytest.raises(KunlianDirectoryNotReadyError):
        await run_round(s.service)
    async with s.sessions() as session:
        assert not (await session.exec(select(Tenant).where(Tenant.parent_tenant_id == 1))).all()


async def test_one_blocked_tenant_does_not_block_other_ready_tenant(onboarding):
    s = onboarding
    await directory.publish(s.repo)
    await run_round(s.service)
    facts = (
        await s.repo.list_onboarding_tenants("fixture", issuer=s.config.issuer, policy_revision=1, max_age_seconds=60)
    )[0]
    source = await s.tenants.read_external_tenant_state(facts.source_key)
    await s.tenants.set_external_tenant_policy(source.source_key, expected_revision=1, enabled=False)
    await directory.publish(
        s.repo,
        tenants=[directory.tenant(), directory.tenant("external-b")],
        members=[directory.member(), directory.member("m2", "s2", "external-b")],
    )
    await run_round(s.service)
    async with s.sessions() as session:
        bindings = (await session.exec(select(KunlianIdentityBinding))).all()
    blocked = next(b for b in bindings if b.external_tenant_id == "external-a")
    from bisheng.common.errcode.sso_sync import KunlianIdentityUnavailableError

    with pytest.raises(KunlianIdentityUnavailableError):
        await s.service.current_qualification(blocked)
    assert (
        await s.service.current_qualification(next(b for b in bindings if b.external_tenant_id == "external-b"))
    ).user_id
