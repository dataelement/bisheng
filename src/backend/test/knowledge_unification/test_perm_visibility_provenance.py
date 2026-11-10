"""F118 controlled visibility provenance survives real Catalog save/reload cycles."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.permission.application.catalog_api import F048CatalogApi, SqlCatalogState
from bisheng.permission.domain.models import PermissionCatalogRelease
from bisheng.permission.domain.schemas import CatalogDraftRequest, VerifiedPermissionTarget
from bisheng.permission.domain.services.catalog_service import CatalogImpactSummary, CatalogService
from bisheng.permission.domain.services.grant_service import (
    CanonicalGrantChange,
    GrantCapability,
    GrantMutationContext,
    GrantService,
)
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
    model_snapshot_for_target,
)
from bisheng.permission.domain.services.model_policy import effective_model_action_codes
from test.knowledge_unification.test_perm_control_snapshot import seed
from test.knowledge_unification.test_perm_control_snapshot import session_factory as session_factory


async def update_and_reload(factory, base_id, actions, key):
    state = SqlCatalogState(session_factory=factory)
    state.grant_references = AsyncMock(return_value={})
    state.model_reference_summaries = AsyncMock(return_value={})
    impact = CatalogImpactSummary("b" * 64, 0, 0, 0, 0, 0)
    service = CatalogService(
        state=state, impact=SimpleNamespace(analyze_draft=AsyncMock(return_value=impact)), projector=object()
    )
    api = F048CatalogApi(state=state, service=service)
    api._impact = SimpleNamespace(describe=AsyncMock(return_value=impact))
    result = await api.create_draft(
        request=CatalogDraftRequest.model_validate(
            {
                "base_release_id": base_id,
                "idempotency_key": key,
                "changes": [{"type": "UPDATE_MODEL", "model_key": "legacy", "action_codes": actions}],
            }
        ),
        operator_id=1,
    )
    loaded = await state.load_snapshot(result["draft_id"])
    # The external projection is outside this regression. Advance only its SQL
    # pointer fixture so the next real draft uses the just-saved release.
    async with factory() as session:
        previous = await session.get(PermissionCatalogRelease, base_id)
        previous.status = "RETIRED"
        current = await session.get(PermissionCatalogRelease, result["draft_id"])
        current.status = "CURRENT"
        await session.commit()
    model = next(row for row in loaded.model_release.models if row.model_key == "legacy")
    snapshot = GrantModelSnapshot(
        model.model_key,
        model.active,
        model.action_codes,
        model.derived_level,
        visibility_only_resource_types=model.visibility_only_resource_types,
        visibility_level=model.visibility_level,
    )
    scoped = model_snapshot_for_target(
        snapshot,
        resource_type="tool",
        applicable_action_codes=effective_model_action_codes(model, loaded.action_release, "tool"),
    )
    return loaded, model, scoped


async def test_real_catalog_update_cycle_restores_original_pure_tier_and_source_revocation(session_factory):
    release_id, _, _ = await seed(session_factory)
    added, active_model, active_scope = await update_and_reload(
        session_factory, release_id, ["download", "edit"], "add-edit"
    )
    assert active_model.visibility_only_resource_types == ("tool",) and active_model.visibility_level == 3
    assert not active_scope.visibility_only and active_scope.action_codes == ("edit",)
    restored, restored_model, restored_scope = await update_and_reload(
        session_factory, added.release_id, ["download"], "remove-edit"
    )
    assert restored_model.visibility_only_resource_types == ("tool",) and restored_model.visibility_level == 3
    assert restored_scope.visibility_only and restored_scope.derived_level == 3 and restored_scope.action_codes == ()
    sources = GrantSourceService()
    original = sources.canonicalize_source(source_id=11, subject_type="user", subject_id="70", source_type="DIRECT")
    current_grant = GrantSnapshot("original-grant", 101, "tool", "t1", restored_scope, True, (original,))
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=101, resource_type="tool", resource_id="t1", resource_version=1, context_version="test"
    )
    context = GrantMutationContext(
        target,
        restored.release_id,
        "s1",
        "m1",
        42,
        "CUSTOM",
        False,
        (GrantCapability(GrantModelSnapshot("owner", True, ("manage_permission",), 4), "owner-source"),),
        (restored_scope,),
        (current_grant,),
    )
    grants = {"legacy": current_grant}
    policy = GrantService(source_service=sources, projection=object(), state=object())
    policy._apply_change(context, grants, CanonicalGrantChange("REMOVE", assignee_id=11, expected_assignee_version=1))
    assert not grants["legacy"].active and grants["legacy"].sources == ()
    assert current_grant.sources[0].source_fingerprint == original.source_fingerprint
