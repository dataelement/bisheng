"""F048 AC-15/164/166: disabled assignment choices keep existing source semantics."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import GrantLevelForbiddenError
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_service import GrantCapability, GrantService
from bisheng.permission.domain.services.grant_source_service import GrantModelSnapshot
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.permission.domain.services.permission_explain_service import PermissionSourceExplanation


def fixture():
    model = GrantModelSnapshot("old-custom", False, ("download", "use"), derived_level=1)
    high = GrantModelSnapshot("high-custom", False, ("edit",), derived_level=3)
    catalog = SimpleNamespace(models=tuple(SimpleNamespace(snapshot=m) for m in (model, high)))
    row = PermissionSourceExplanation(
        source_id=11,
        source_version=2,
        subject_type="department",
        subject_id="310",
        userset_relation="member",
        include_children=False,
        source_type="DEPARTMENT",
        model_key=model.model_key,
        model_level=1,
        scope="LOCAL",
        inherited_from=None,
        protected=False,
        editable=True,
    )
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id="space",
        resource_version=3,
        context_version="test",
    )
    service = object.__new__(F048PermissionRuntime)
    service._runtime_catalog = AsyncMock(return_value=catalog)
    service._require_manage_permission = AsyncMock()
    service._require_current_target = AsyncMock(return_value=SimpleNamespace(mode="CUSTOM"))
    service._state = SimpleNamespace(load_source_page=AsyncMock(return_value=((row,), False)))
    service._grants = GrantService(source_service=object(), projection=object(), state=object())
    capability = GrantCapability(
        model=GrantModelSnapshot("manager", True, ("manage_permission",), derived_level=2),
        source_key="manager",
    )
    service._grant_capabilities = AsyncMock(return_value=(capability,))
    return service, PermissionActor(user_id=9, current_tenant_id=7), target, row


async def test_roster_editability_uses_existing_source_level_not_assignability():
    service, actor, target, row = fixture()
    result, more = await service.list_permission_sources_page(actor=actor, target=target, after_id=0, limit=20)
    assert more is False and result == (row,)
    assert await service.manageable_model_keys(actor=actor, target=target) == frozenset({"old-custom"})
    call = service._state.load_source_page.call_args.kwargs
    assert call["limit"] == 20 and call["models"][0].active is False
    models = tuple(item.snapshot for item in (await service._runtime_catalog()).models)
    capabilities = await service._grant_capabilities(actor, target)
    assert service._grants.grantable_models_for_capabilities(models=models, capabilities=capabilities) == ()


async def test_existing_higher_level_source_remains_read_only():
    service, actor, target, row = fixture()
    service._state.load_source_page.return_value = ((replace(row, model_key="high-custom", model_level=3),), False)
    rows, _ = await service.list_permission_sources_page(actor=actor, target=target, after_id=0, limit=20)
    assert rows[0].editable is False


@pytest.mark.parametrize("change", [{"protected": True, "editable": False}, {"scope": "INHERITED", "editable": False}])
async def test_protected_and_inherited_sources_keep_read_only(change):
    service, actor, target, row = fixture()
    service._state.load_source_page.return_value = ((replace(row, **change),), False)
    rows, _ = await service.list_permission_sources_page(actor=actor, target=target, after_id=0, limit=20)
    assert rows[0].editable is False
    service._grant_capabilities.assert_not_called()


async def test_source_roster_refuses_before_read_when_reader_cannot_manage():
    service, actor, target, _ = fixture()
    service._require_manage_permission.side_effect = GrantLevelForbiddenError()
    with pytest.raises(GrantLevelForbiddenError):
        await service.list_permission_sources_page(actor=actor, target=target, after_id=0, limit=20)
    service._state.load_source_page.assert_not_called()


def test_same_level_policy_is_shared_by_old_binding_and_new_assignment():
    service, _, _, _ = fixture()
    model = GrantModelSnapshot("same-level", False, ("download",), derived_level=2)
    capability = GrantCapability(
        model=GrantModelSnapshot("manager", True, ("manage_permission",), derived_level=2),
        source_key="manager",
    )
    policy = service._grants
    assert policy.manageable_models_for_capabilities(models=(model,), capabilities=(capability,)) == ()
    allowed = replace(capability, model=replace(capability.model, allow_same_level=True))
    assert policy.manageable_models_for_capabilities(models=(model,), capabilities=(allowed,)) == (model,)
    assert policy.grantable_models_for_capabilities(models=(model,), capabilities=(allowed,)) == ()
