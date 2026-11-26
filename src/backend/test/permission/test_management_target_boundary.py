"""AC-53: platform action privileges cannot widen an admitted tenant target."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError, PermissionPublishNotReadyError
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


@pytest.mark.parametrize("error", [PermissionInvalidResourceError, PermissionPublishNotReadyError])
@pytest.mark.parametrize("super_admin", [False, True])
async def test_listing_denies_broken_projection_without_losing_valid_candidates(monkeypatch, error, super_admin):
    from bisheng.permission.domain.services.permission_action_service import PermissionActor

    async def load(*, resource_id):
        if resource_id == "broken":
            raise error()
        return SimpleNamespace(tenant_id=60)

    target = SimpleNamespace(tenant_id=60)
    registry = SimpleNamespace(
        port_for=lambda _: SimpleNamespace(load_permission_record=load), resolve=AsyncMock(return_value=target)
    )
    runtime = SimpleNamespace(batch_check_actions=AsyncMock(return_value=(True,)))
    actor = PermissionActor(user_id=7, current_tenant_id=60, super_admin=super_admin)
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(business, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(business, "resolve_permission_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(business, "_require_creation_ready", AsyncMock())
    with management_tenant_scope(60):
        result = await business.batch_check_business_actions(
            object(), resource_type="assistant", resource_ids=("broken", "ready"), actions=("visible",)
        )
    assert result == {"broken": frozenset(), "ready": frozenset({"visible"})}
    if super_admin:
        registry.resolve.assert_not_awaited()
        runtime.batch_check_actions.assert_not_awaited()
    else:
        registry.resolve.assert_awaited_once()
        runtime.batch_check_actions.assert_awaited_once_with(actor, (target,), "visible")


@pytest.mark.parametrize("error", [PermissionInvalidResourceError, PermissionPublishNotReadyError])
async def test_single_resource_still_rejects_an_unreadable_projection(monkeypatch, error):
    registry = SimpleNamespace(
        port_for=lambda _: SimpleNamespace(load_permission_record=AsyncMock(side_effect=error()))
    )
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    with management_tenant_scope(60), pytest.raises(error):
        await business.check_business_action(object(), resource_type="assistant", resource_id="broken", action="edit")


async def test_listing_does_not_hide_an_unexpected_loader_failure(monkeypatch):
    registry = SimpleNamespace(
        port_for=lambda _: SimpleNamespace(load_permission_record=AsyncMock(side_effect=RuntimeError("DB unavailable")))
    )
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    with management_tenant_scope(60), pytest.raises(RuntimeError, match="DB unavailable"):
        await business._admitted_management_targets("assistant", ("broken", "ready"))
