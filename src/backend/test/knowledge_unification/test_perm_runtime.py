"""F118 visibility admission and rejection of retired permission actions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.open_api import PersonalTokenDataScopeError
from bisheng.common.errcode.permission import InvalidCatalogActionError
from bisheng.permission.application import business_authorization as business
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import F048PermissionService, PermissionActor


def target(tenant=101, resource_type="tool"):
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=tenant, resource_type=resource_type, resource_id="t1", resource_version=1, context_version="test"
    )


def decision():
    fga = SimpleNamespace(check=AsyncMock(return_value=True), batch_check=AsyncMock(return_value=[True]))
    service = F048PermissionService(
        catalog=SimpleNamespace(
            ensure_runtime_ready=AsyncMock(),
            is_action_effective=AsyncMock(return_value=True),
            effective_actions=AsyncMock(return_value=("edit", "delete")),
        ),
        scope_fence=SimpleNamespace(ensure_readable=AsyncMock(return_value=False)),
        marker=SimpleNamespace(consistency_for=AsyncMock(return_value=None)),
        fga=fga,
        list_policy=SimpleNamespace(allows=AsyncMock(return_value=True)),
    )
    return service, fga


@pytest.mark.parametrize("old_action", ["use", "use_kb"])
@pytest.mark.parametrize("super_admin", [False, True])
async def test_retired_actions_cannot_reach_fga_or_identity_shortcuts(old_action, super_admin):
    service, fga = decision()
    actor = PermissionActor(user_id=42, current_tenant_id=101, super_admin=super_admin)
    with pytest.raises(InvalidCatalogActionError):
        await service.check_action(actor, target(), old_action)
    with pytest.raises(InvalidCatalogActionError):
        await service.batch_check_actions(actor, (target(),), old_action)
    with pytest.raises(InvalidCatalogActionError):
        await service.list_action_objects(actor, resource_type="tool", action=old_action, max_results=10)
    fga.check.assert_not_awaited()
    fga.batch_check.assert_not_awaited()


async def test_visible_keeps_tenant_and_narrowed_token_denials(monkeypatch):
    monkeypatch.setattr(
        "bisheng.permission.domain.services.permission_action_service.get_data_scope_resolver", lambda: None
    )
    service, fga = decision()
    assert not await service.check_action(PermissionActor(user_id=42, current_tenant_id=202), target(), "visible")
    fga.check.assert_not_called()
    with pytest.raises(PersonalTokenDataScopeError):
        await service.check_action(
            PermissionActor(user_id=42, current_tenant_id=101, data_scope="OWNED"), target(), "visible"
        )
    fga.check.assert_not_called()


async def test_business_single_and_batch_request_visibility_without_an_alias(monkeypatch):
    monkeypatch.setattr(business, "_require_creation_ready", AsyncMock())
    actor = PermissionActor(subject_type="service_account", subject_id=42, tenant_id=101)
    registry = SimpleNamespace(resolve=AsyncMock(return_value=target()))
    runtime = SimpleNamespace(
        check_action=AsyncMock(return_value=True), batch_check_actions=AsyncMock(return_value=(True,))
    )
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(business, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(business, "resolve_permission_actor", AsyncMock(return_value=actor))
    assert await business.check_business_action(object(), resource_type="tool", resource_id="t1", action="visible")
    assert registry.resolve.call_args.kwargs["action"] == "visible"
    assert runtime.check_action.call_args.args[-1] == "visible"
    result = await business.batch_check_business_actions(
        object(), resource_type="tool", resource_ids=("t1",), actions=("visible",)
    )
    assert result == {"t1": frozenset({"visible"})}
    assert runtime.batch_check_actions.call_args.args[-1] == "visible"


@pytest.mark.parametrize("action", ["use", "use_kb"])
async def test_business_retired_actions_fail_before_any_resource_or_actor_lookup(monkeypatch, action):
    lookup = AsyncMock()
    monkeypatch.setattr(business, "resolve_permission_actor", lookup)
    monkeypatch.setattr(business, "get_f048_resource_registry", lookup)
    monkeypatch.setattr(business, "_require_creation_ready", lookup)
    with pytest.raises(InvalidCatalogActionError):
        await business.check_business_action(object(), resource_type="tool", resource_id="t1", action=action)
    with pytest.raises(InvalidCatalogActionError):
        await business.batch_check_business_actions(
            object(), resource_type="tool", resource_ids=("t1",), actions=(action,)
        )
    lookup.assert_not_awaited()


async def test_retired_catalog_actions_are_reported_instead_of_silently_hidden():
    service, _ = decision()
    assert await service.effective_actions("tool") == ("edit", "delete")
    service._catalog.effective_actions.return_value = ("use", "edit")
    with pytest.raises(InvalidCatalogActionError):
        await service.effective_actions("tool")
