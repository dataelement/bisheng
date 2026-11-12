"""覆盖 AC: AC-01, AC-02, AC-09, AC-10, AC-11, AC-13。"""

from dataclasses import replace
from importlib import import_module
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from bisheng.common.errcode.sso_sync import KunlianBindingConflictError, KunlianIdentityUnavailableError
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import Tenant, UserTenant
from test.fixtures import kunlian_onboarding

onboarding_store = kunlian_onboarding.onboarding_store


def application(store, **kwargs):
    module = import_module("bisheng.tenant.application.external_provision")
    return module, module.KunlianExternalTenantApplication(
        module.TenantExternalProvisionRepository(store.sessions), **kwargs
    )


def command(module, tenant="A", **kwargs):
    return module.ExternalTenantCommand(
        "fixture", "https://idp.fixture", tenant, "同名", "batch-1", "a" * 64, 1, **kwargs
    )


async def test_distinct_sources_idempotent_receipt_and_name_changes_do_not_merge(onboarding_store):
    module, app = application(onboarding_store)
    a, b = command(module), command(module, "B")
    operation = await app.reserve_external_tenant(a)
    first = await app.ensure_external_tenant(a, operation=operation)
    assert await app.read_external_tenant_receipt(operation) == first
    assert await app.ensure_external_tenant(a, operation=operation) == first
    other = await app.ensure_external_tenant(b, operation=await app.reserve_external_tenant(b))
    assert first.local_tenant_id != other.local_tenant_id
    renamed = replace(a, display_name="更名", source_revision="b" * 64)
    newer = await app.reserve_external_tenant(renamed, expected_fence=operation.fence)
    assert (await app.ensure_external_tenant(renamed, operation=newer)).local_tenant_id == first.local_tenant_id
    with pytest.raises(KunlianBindingConflictError):
        await app.ensure_external_tenant(a, operation=operation)
    async with onboarding_store.sessions() as session:
        assert len((await session.exec(select(Tenant))).all()) == 3
        assert not (await session.exec(select(UserTenant))).all()
        children = (await session.exec(select(Tenant).where(Tenant.id != 1))).all()
        assert all(
            t.parent_tenant_id == 1 and t.create_user is None and not t.share_default_to_children for t in children
        )


async def test_source_conflict_policy_cas_and_manual_target_are_preserved(onboarding_store):
    module, app = application(onboarding_store)
    a = command(module)
    operation = await app.reserve_external_tenant(a)
    receipt = await app.ensure_external_tenant(a, operation=operation)
    with pytest.raises(KunlianBindingConflictError):
        await app.reserve_external_tenant(replace(a, connection_id="other"))
    revision = await app.set_external_tenant_policy(a.source_key, expected_revision=1, enabled=False)
    assert revision == 2
    with pytest.raises(KunlianIdentityUnavailableError):
        await app.ensure_external_tenant(a, operation=operation)
    with pytest.raises(KunlianBindingConflictError):
        await app.set_external_tenant_policy(a.source_key, expected_revision=1, enabled=False)
    await app.set_external_tenant_policy(a.source_key, expected_revision=2, enabled=True)
    manual = command(module, "manual", manual_tenant_id=receipt.local_tenant_id)
    # 同一本地目标已归其他来源, 不能以人工映射重新认领。
    with pytest.raises(KunlianBindingConflictError):
        await app.ensure_external_tenant(manual, operation=await app.reserve_external_tenant(manual))


async def test_structure_rollback_and_post_commit_failure_recover_same_target(onboarding_store):
    module, app = application(onboarding_store)
    from bisheng.department.application.external_tenant_anchor import ensure_external_tenant_anchor

    async def fail_after_anchor(*args, **kwargs):
        await ensure_external_tenant_anchor(*args, **kwargs)
        raise RuntimeError("fixture rollback")

    value = command(module)
    operation = await app.reserve_external_tenant(value)
    _, broken = application(onboarding_store, anchor_provider=fail_after_anchor)
    with pytest.raises(RuntimeError, match="fixture rollback"):
        await broken.ensure_external_tenant(value, operation=operation)
    async with onboarding_store.sessions() as session:
        assert len((await session.exec(select(Tenant))).all()) == 1
        assert len((await session.exec(select(Department))).all()) == 1
    projector = AsyncMock(side_effect=RuntimeError("fixture receipt lost"))
    _, partial = application(onboarding_store, structure_projector=projector)
    with pytest.raises(RuntimeError, match="fixture receipt lost"):
        await partial.ensure_external_tenant(value, operation=operation)
    first = await app.ensure_external_tenant(value, operation=operation)
    async with onboarding_store.sessions() as session:
        assert len((await session.exec(select(Tenant))).all()) == 2
    assert (await app.read_external_tenant_receipt(operation)).local_tenant_id == first.local_tenant_id


async def test_existing_manual_mapping_keeps_original_structure_and_name(onboarding_store):
    module, app = application(onboarding_store)
    async with onboarding_store.sessions() as session:
        session.add(Tenant(id=77, tenant_code="manual", tenant_name="原本地名称", parent_tenant_id=1, root_dept_id=77))
        session.add(
            Department(
                id=77,
                dept_id="manual",
                name="原部门",
                tenant_id=1,
                parent_id=1,
                path="/1/77/",
                is_tenant_root=1,
                mounted_tenant_id=77,
            )
        )
        await session.commit()
    command_value = command(module, manual_tenant_id=77)
    result = await app.ensure_external_tenant(command_value, operation=await app.reserve_external_tenant(command_value))
    assert result.local_tenant_id == 77 and result.anchor_department_id == 77
    async with onboarding_store.sessions() as session:
        assert (await session.exec(select(Tenant).where(Tenant.id == 77))).one().tenant_name == "原本地名称"
        assert len((await session.exec(select(Tenant))).all()) == 2


@pytest.mark.parametrize("changes", [{"active": False}, {"directory_complete": False}, {"policy_revision": 0}])
async def test_untrusted_or_inactive_facts_do_not_reserve(onboarding_store, changes):
    module, app = application(onboarding_store)
    with pytest.raises((KunlianBindingConflictError, KunlianIdentityUnavailableError)):
        await app.reserve_external_tenant(replace(command(module), **changes))
