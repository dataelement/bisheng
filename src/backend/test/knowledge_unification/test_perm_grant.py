"""F118 manageable pure-visible grants. 覆盖 AC: AC-78, AC-81, AC-83."""

from dataclasses import replace

import pytest

from bisheng.common.errcode.permission import GrantLevelForbiddenError, ProtectedAssignmentMutationError
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
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
)
from test.knowledge_unification.test_perm_source_snapshot import scoped


def context(*, active=True, actor_level=4):
    model = scoped(active=active)
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=101, resource_type="tool", resource_id="t1", resource_version=1, context_version="test"
    )
    manager = GrantCapability(
        GrantModelSnapshot("manager", True, ("manage_permission",), derived_level=actor_level), "actor-manager"
    )
    return GrantMutationContext(target, 1, "s1", "m1", 42, "CUSTOM", False, (manager,), (model,), ())


def service():
    return GrantService(source_service=GrantSourceService(), projection=object(), state=object())


def test_marked_empty_model_is_grantable_and_manageable_at_original_tier():
    ctx = context()
    policy = service()
    assert policy.grantable_models(ctx) == ctx.models
    assert policy.require_grantable_model(ctx, "mixed") == ctx.models[0]
    assert policy.require_manageable_existing_model(ctx, "mixed") == ctx.models[0]


def test_inactive_existing_model_remains_manageable_without_new_grants():
    ctx = context(active=False)
    policy = service()
    assert policy.grantable_models(ctx) == ()
    assert policy.manageable_models_for_capabilities(models=ctx.models, capabilities=ctx.capabilities) == ctx.models
    assert policy.require_manageable_existing_model(ctx, "mixed") == ctx.models[0]


def test_original_tier_cannot_be_delegated_by_lower_manager_or_pure_viewer():
    ctx = context(actor_level=2)
    with pytest.raises(GrantLevelForbiddenError):
        service().require_grantable_model(ctx, "mixed")
    pure_actor = replace(ctx, capabilities=(GrantCapability(ctx.models[0], "pure-viewer"),))
    with pytest.raises(GrantLevelForbiddenError):
        service().assert_roster_access(pure_actor)


def test_removal_of_one_source_preserves_other_same_subject_contribution():
    ctx = context(active=False)
    policy = service()
    first = policy._sources.canonicalize_source(source_id=1, subject_type="user", subject_id="70", source_type="DIRECT")
    second = policy._sources.canonicalize_source(
        source_id=2, subject_type="user", subject_id="70", source_type="OTHER", source_ref="business"
    )
    original = GrantSnapshot("g1", 101, "tool", "t1", ctx.models[0], True, (first, second))
    grants = {"mixed": original}
    delta = policy._apply_change(
        ctx, grants, CanonicalGrantChange("REMOVE", assignee_id=1, expected_assignee_version=1)
    )
    assert delta == () and grants["mixed"].sources == (second,) and grants["mixed"].active
    assert first.source_fingerprint != second.source_fingerprint


def test_protected_source_cannot_be_removed_with_pure_visibility_exception():
    ctx = context()
    policy = service()
    source = policy._sources.canonicalize_source(
        source_id=1, subject_type="user", subject_id="70", source_type="DIRECT", protected=True
    )
    grants = {"mixed": GrantSnapshot("g1", 101, "tool", "t1", ctx.models[0], True, (source,))}
    with pytest.raises(ProtectedAssignmentMutationError):
        policy._apply_change(ctx, grants, CanonicalGrantChange("REMOVE", assignee_id=1, expected_assignee_version=1))
