"""F118 resource permission DTO output. 覆盖 AC: AC-78, AC-81, AC-83."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.permission.application.resource_api import F048ResourcePermissionApi
from bisheng.permission.domain.schemas import GrantMutationRequest
from bisheng.permission.domain.services.grant_source_service import GrantSnapshot, GrantSourceService
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.permission.domain.services.permission_explain_service import PermissionSourceExplanation
from test.knowledge_unification.test_perm_runtime_snapshot import catalog, target


def api():
    current = catalog()
    model = current.model_for_target(current.models[1].snapshot, resource_type="tool")
    row = PermissionSourceExplanation(
        source_id=1,
        source_version=1,
        subject_type="user",
        subject_id="70",
        userset_relation=None,
        include_children=False,
        source_type="DIRECT",
        model_key="mixed",
        model_level=1,
        scope="LOCAL",
        inherited_from=None,
        protected=False,
        editable=True,
    )
    runtime = SimpleNamespace(
        current_catalog=AsyncMock(return_value=current),
        require_manage_permission=AsyncMock(),
        grantable_models=AsyncMock(return_value=(model,)),
        list_permission_sources_page=AsyncMock(return_value=((row,), False)),
        allocate_source_ids=AsyncMock(return_value=()),
        manageable_model_keys=AsyncMock(return_value=frozenset({"mixed"})),
    )
    subjects = SimpleNamespace(
        display_names=AsyncMock(return_value={}), resource_display_names=AsyncMock(return_value={})
    )
    result = F048ResourcePermissionApi(
        resources=SimpleNamespace(resolve=AsyncMock(return_value=target())), runtime=runtime, subjects=subjects
    )
    return result, runtime, model


async def test_grantable_model_serializes_pure_visibility_flag():
    resource_api, _, _ = api()
    result = await resource_api.get_grantable_models(
        resource_type="tool", resource_id="t1", actor=PermissionActor(user_id=42, current_tenant_id=101)
    )
    assert result[0]["visibility_only"] is True and result[0]["level"] == 3


async def test_roster_uses_target_scoped_metadata_and_original_tier():
    resource_api, _, _ = api()
    result = await resource_api.list_grants(
        cursor=None,
        page_size=20,
        resource_type="tool",
        resource_id="t1",
        actor=PermissionActor(user_id=42, current_tenant_id=101),
    )
    model = result["data"][0]["model"]
    assert model["visibility_only"] is True and model["level"] == 3


async def test_mutation_result_serializes_target_snapshot():
    resource_api, runtime, model = api()
    source = GrantSourceService().canonicalize_source(
        source_id=2, subject_type="user", subject_id="70", source_type="OTHER", source_ref="retained"
    )
    runtime.mutate_grants = AsyncMock(
        return_value=SimpleNamespace(
            resource_version=2, grants=(GrantSnapshot("g1", 101, "tool", "t1", model, True, (source,)),)
        )
    )
    request = GrantMutationRequest.model_validate(
        {
            "expected_resource_version": 1,
            "expected_catalog_release_id": 1,
            "idempotency_key": "remove-one",
            "changes": [{"op": "REMOVE", "assignee_id": "1", "expected_assignee_version": 1}],
        }
    )
    result = await resource_api.mutate_grants(
        resource_type="tool",
        resource_id="t1",
        actor=PermissionActor(user_id=42, current_tenant_id=101),
        request=request,
    )
    assert result["items"][0]["model"]["visibility_only"] is True and result["items"][0]["model"]["level"] == 3
