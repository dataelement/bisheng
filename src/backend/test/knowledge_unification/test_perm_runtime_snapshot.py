"""F118 scoped runtime snapshots. 覆盖 AC: AC-78, AC-80, AC-81, AC-83."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.permission.application.control_state import RuntimeCatalogSnapshot, RuntimeModelSnapshot
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.application.sql_runtime import stable_grant_key
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_service import GrantCapability, GrantService
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor


def catalog():
    return RuntimeCatalogSnapshot(
        1,
        "r1",
        1,
        "a" * 64,
        "s1",
        "m1",
        "b" * 64,
        (
            RuntimeModelSnapshot(
                GrantModelSnapshot(
                    "viewer",
                    True,
                    ("download",),
                    1,
                    visibility_only_resource_types=("tool", "linsight_skill"),
                    visibility_level=1,
                ),
                "Viewer",
                "STANDARD",
                1,
            ),
            RuntimeModelSnapshot(
                GrantModelSnapshot(
                    "mixed", True, ("download",), 1, visibility_only_resource_types=("tool",), visibility_level=3
                ),
                "Mixed",
                "CUSTOM",
                1,
            ),
        ),
        action_resource_scopes=(("download", ("folder", "knowledge_file")),),
    )


def target():
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=101, resource_type="tool", resource_id="t1", resource_version=1, context_version="test"
    )


def runtime():
    service = object.__new__(F048PermissionRuntime)
    service._runtime_catalog = AsyncMock(return_value=catalog())
    service._require_current_target = AsyncMock(return_value=SimpleNamespace(mode="CUSTOM"))
    service._sources = GrantSourceService()
    service._state = SimpleNamespace(
        load_grants=AsyncMock(return_value=()), load_visible_sources=AsyncMock(return_value=())
    )
    service._grant_capabilities = AsyncMock(
        return_value=(GrantCapability(GrantModelSnapshot("owner", True, ("manage_permission",), 4), "actor"),)
    )
    service._grants = GrantService(source_service=service._sources, projection=object(), state=object())
    return service


async def test_grant_context_uses_target_level_and_actions():
    service = runtime()
    context = await service.build_grant_context(
        actor=PermissionActor(user_id=42, current_tenant_id=101), target=target()
    )
    mixed = next(model for model in context.models if model.model_key == "mixed")
    assert mixed.visibility_only and mixed.derived_level == 3 and mixed.action_codes == ()
    assert service._state.load_grants.call_args.kwargs["models"] == context.models
    assert service._grants.grantable_models(context) == context.models


def test_tenant_members_use_current_pure_visible_model_and_stable_source():
    service = runtime()
    mutation = service.tenant_use_grant(target(), catalog())
    assert mutation.grant.model.model_key == "viewer"
    assert mutation.grant.model.visibility_only and mutation.grant.model.action_codes == ()
    assert mutation.grant.grant_id == stable_grant_key(
        tenant_id=101, resource_type="tool", resource_id="t1", model_key="viewer"
    )
    source = mutation.grant.sources[0]
    assert source.subject_type == "tenant" and source.subject_id == "101" and source.source_type == "TENANT"
    assert source.source_ref == "tenant:101#member"


def test_model_scoping_keeps_existing_projection_source_and_plan_deltas():
    sources = GrantSourceService()
    source = sources.canonicalize_source(source_id=10, subject_type="user", subject_id="42", source_type="DIRECT")
    before = GrantSnapshot("g1", 101, "tool", "t1", GrantModelSnapshot("mixed", True, ("use",), 3), False, ())
    after = GrantSnapshot(
        "g1",
        101,
        "tool",
        "t1",
        catalog().model_for_target(catalog().models[1].snapshot, resource_type="tool"),
        False,
        (),
    )
    old_plan = sources.add_source(before, source)
    new_plan = sources.add_source(after, source)
    assert old_plan.deltas == new_plan.deltas and old_plan.grant.sources == new_plan.grant.sources
