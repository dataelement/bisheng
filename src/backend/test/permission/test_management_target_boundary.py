"""AC-53: platform action privileges cannot widen an admitted tenant target."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.core.context.tenant import management_tenant_scope
from bisheng.permission.application import business_authorization as business


@pytest.mark.parametrize("owner,allowed", [(60, True), (65, False), (1, False)])
async def test_super_action_shortcut_still_proves_business_target(monkeypatch, owner, allowed):
    loader = AsyncMock(return_value=SimpleNamespace(tenant_id=owner))
    registry = SimpleNamespace(port_for=lambda _: SimpleNamespace(load_permission_record=loader))
    actor = SimpleNamespace(super_admin=True, data_scope=business.DATA_SCOPE_ALL)
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(business, "_require_creation_ready", AsyncMock())
    monkeypatch.setattr(business, "resolve_permission_actor", AsyncMock(return_value=actor))
    with management_tenant_scope(60):
        if allowed:
            assert await business.check_business_action(
                object(), resource_type="workflow", resource_id="a", action="edit"
            )
        else:
            with pytest.raises(PermissionInvalidResourceError):
                await business.check_business_action(object(), resource_type="workflow", resource_id="a", action="edit")


async def test_listing_proves_management_targets_in_one_batch(monkeypatch):
    single = AsyncMock(side_effect=AssertionError("listing must not load one id at a time"))
    batch = AsyncMock(
        return_value={
            "1": SimpleNamespace(tenant_id=60),
            "2": SimpleNamespace(tenant_id=99),
            "3": None,
        }
    )
    registry = SimpleNamespace(
        port_for=lambda _: SimpleNamespace(load_permission_record=single, load_permission_records=batch)
    )
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    with management_tenant_scope(60):
        admitted = await business._admitted_management_targets("knowledge_space", ("1", "2", "3", "4"))
    assert admitted == ("1",)
    batch.assert_awaited_once_with(resource_ids=("1", "2", "3", "4"))
    single.assert_not_awaited()


async def test_listing_reads_ids_one_by_one_when_no_batch_proof_exists(monkeypatch):
    single = AsyncMock(side_effect=lambda *, resource_id: SimpleNamespace(tenant_id=60) if resource_id == "1" else None)
    registry = SimpleNamespace(port_for=lambda _: SimpleNamespace(load_permission_record=single))
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    with management_tenant_scope(60):
        admitted = await business._admitted_management_targets("knowledge_space", ("1", "2"))
    assert admitted == ("1",)
    assert single.await_count == 2


async def test_actual_skill_port_supports_the_target_proof_without_authorizing(monkeypatch):
    from bisheng.linsight.domain.services.skill_permission import SkillPermissionAdapter

    repository = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(tenant_id=60)))
    adapter = SkillPermissionAdapter(object(), repository=repository)
    assert (await adapter.load_permission_record(resource_id="7")).tenant_id == 60
    assert await adapter.load_permission_record(resource_id="invalid") is None
    repository.get.assert_awaited_once_with(7)
