"""覆盖 AC: AC-01, AC-02, AC-10, AC-11。"""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from bisheng.common.errcode.sso_sync import KunlianDirectoryNotReadyError, KunlianSyncConflictError
from bisheng.database.models.tenant import Tenant
from bisheng.sso_sync.domain.models.kunlian import KunlianIdentityBinding, KunlianSyncBatch, KunlianTenantBinding
from test.sso import test_kunlian_directory as directory
from test.sso import test_kunlian_tenant_onboarding as fixtures

onboarding = fixtures.onboarding
onboarding_store = fixtures.onboarding_store


async def test_late_owner_receipt_cannot_bind_old_batch_and_next_round_reuses_structure(onboarding, monkeypatch):
    s = onboarding
    await directory.publish(s.repo)
    facts = (
        await s.repo.list_onboarding_tenants("fixture", issuer=s.config.issuer, policy_revision=1, max_age_seconds=60)
    )[0]
    original = s.tenants.read_external_tenant_receipt

    async def late(operation):
        receipt = await original(operation)
        await directory.publish(s.repo)
        return receipt

    monkeypatch.setattr(s.tenants, "read_external_tenant_receipt", late)
    with pytest.raises(KunlianSyncConflictError):
        await s.service._provision_tenant(facts)
    async with s.sessions() as session:
        assert not (await session.exec(select(KunlianTenantBinding))).all()
        assert len((await session.exec(select(Tenant).where(Tenant.parent_tenant_id == 1))).all()) == 1
    monkeypatch.setattr(s.tenants, "read_external_tenant_receipt", original)
    await fixtures.run_round(s.service)
    async with s.sessions() as session:
        assert len((await session.exec(select(Tenant).where(Tenant.parent_tenant_id == 1))).all()) == 1
        binding = (await session.exec(select(KunlianIdentityBinding))).one()
    assert (await s.service.current_qualification(binding)).role_ids


async def test_failed_base_access_is_recovered_even_after_original_projection_succeeded(onboarding, monkeypatch):
    s = onboarding
    await directory.publish(s.repo)
    await s.service.recover("fixture", stage="tenants")
    await s.service.recover("fixture", stage="projection")
    original = s.access.ensure_external_basic_access
    failed = AsyncMock(side_effect=KunlianDirectoryNotReadyError())
    monkeypatch.setattr(s.access, "ensure_external_basic_access", failed)
    assert (await s.service.recover("fixture", stage="basic_access"))["failed"] == 1
    async with s.sessions() as session:
        binding = (await session.exec(select(KunlianIdentityBinding))).one()
        assert binding.projection_status == "SUCCEEDED"
    monkeypatch.setattr(s.access, "ensure_external_basic_access", original)
    assert (await s.service.recover("fixture", stage="basic_access"))["succeeded"] == 1
    assert (await s.service.current_qualification(binding)).role_ids


async def test_stale_published_batch_does_not_drive_onboarding(onboarding):
    s = onboarding
    lease = await directory.publish(s.repo)
    async with s.sessions() as session:
        batch = await session.get(KunlianSyncBatch, lease.batch_id)
        batch.completed_at -= timedelta(seconds=61)
        session.add(batch)
        await session.commit()
    with pytest.raises(KunlianDirectoryNotReadyError):
        await fixtures.run_round(s.service)


async def test_manual_mapping_is_preserved_while_missing_basic_access_is_added(onboarding):
    from bisheng.database.models.department import Department

    s = onboarding
    async with s.sessions() as session:
        session.add(Tenant(id=77, tenant_code="manual", tenant_name="人工名称", parent_tenant_id=1, root_dept_id=77))
        session.add(
            Department(
                id=77,
                dept_id="manual",
                name="原锚点",
                tenant_id=1,
                parent_id=1,
                path="/1/77/",
                is_tenant_root=1,
                mounted_tenant_id=77,
            )
        )
        await session.commit()
    await s.repo.bind_tenant("fixture", "external-a", verified_local_tenant_id=77, expected_revision=None)
    await directory.publish(s.repo)
    # 原资料投影已经成功, 独立恢复仍会补上基础资格。
    key = s.repo.identity_key(s.config.issuer, "external-a", "subject-1")
    await s.projection.project_identity(key)
    await fixtures.run_round(s.service)
    mapping = await s.repo.get_tenant_binding("fixture", "external-a")
    assert mapping.local_tenant_id == 77 and mapping.revision == 1 and mapping.materialized
    async with s.sessions() as session:
        assert (await session.get(Tenant, 77)).tenant_name == "人工名称"
        assert len((await session.exec(select(Tenant))).all()) == 2
    assert (await s.service.current_qualification(await s.repo.get_binding(key))).role_ids
