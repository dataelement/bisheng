"""F118 legacy use protocol compatibility. 覆盖 AC: AC-35, AC-78, AC-79, AC-82, AC-83."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.open_api import PersonalTokenDataScopeError
from bisheng.permission.application import business_authorization as business
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import F048PermissionService, PermissionActor


def target(tenant=101):
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=tenant, resource_type="tool", resource_id="t1", resource_version=1, context_version="test"
    )


def decision():
    fga = SimpleNamespace(check=AsyncMock(return_value=True), batch_check=AsyncMock(return_value=[True]))
    service = F048PermissionService(
        catalog=SimpleNamespace(
            ensure_runtime_ready=AsyncMock(),
            is_action_effective=AsyncMock(return_value=True),
            effective_actions=AsyncMock(return_value=("use", "download")),
        ),
        scope_fence=SimpleNamespace(ensure_readable=AsyncMock(return_value=False)),
        marker=SimpleNamespace(consistency_for=AsyncMock(return_value=None)),
        fga=fga,
        list_policy=SimpleNamespace(allows=AsyncMock(return_value=True)),
    )
    return service, fga


@pytest.mark.parametrize("old_action", ["use", "use_kb"])
async def test_legacy_use_checks_final_visible_not_a_concrete_action(old_action):
    service, fga = decision()
    assert await service.check_action(PermissionActor(user_id=42, current_tenant_id=101), target(), old_action)
    assert fga.check.call_args.kwargs["relation"] == "visible"
    assert "use" not in await service.effective_actions("tool")


async def test_legacy_use_keeps_tenant_and_narrowed_token_denials():
    service, fga = decision()
    assert not await service.check_action(PermissionActor(user_id=42, current_tenant_id=202), target(), "use")
    fga.check.assert_not_called()
    with pytest.raises(PersonalTokenDataScopeError):
        await service.check_action(
            PermissionActor(user_id=42, current_tenant_id=101, data_scope="OWNED"), target(), "use"
        )
    fga.check.assert_not_called()


async def test_business_single_and_batch_adapt_before_target_resolution(monkeypatch):
    actor = PermissionActor(subject_type="service_account", subject_id=42, tenant_id=101)
    registry = SimpleNamespace(resolve=AsyncMock(return_value=target()))
    runtime = SimpleNamespace(
        check_action=AsyncMock(return_value=True), batch_check_actions=AsyncMock(return_value=(True,))
    )
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(business, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(business, "resolve_permission_actor", AsyncMock(return_value=actor))
    assert await business.check_business_action(object(), resource_type="tool", resource_id="t1", action="use")
    assert registry.resolve.call_args.kwargs["action"] == "visible"
    assert runtime.check_action.call_args.args[-1] == "visible"
    result = await business.batch_check_business_actions(
        object(), resource_type="tool", resource_ids=("t1",), actions=("use",)
    )
    assert result == {"t1": frozenset({"use"})}  # legacy caller's response label, no new Catalog action
    assert runtime.batch_check_actions.call_args.args[-1] == "visible"
