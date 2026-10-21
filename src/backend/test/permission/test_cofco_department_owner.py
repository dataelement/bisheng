"""Department owner handover keeps provenance and the ordinary protection fence."""

from dataclasses import replace

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError, ProtectedAssignmentMutationError
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_service import CanonicalGrantChange
from test.permission.test_f048_grant_policy import _context, _service


def context():
    original = _context(capabilities=(), system_authorized=True)
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id="42",
        resource_version=4,
        context_version="department:42:7",
    )
    return replace(
        original, target=target, grants=tuple(replace(g, resource_type="knowledge_space") for g in original.grants)
    )


def source(sources, user_id, *, creator=False, source_id=101):
    return sources.canonicalize_source(
        source_id=source_id,
        subject_type="user",
        subject_id=str(user_id),
        source_type="CREATOR" if creator else "SPACE_MEMBERSHIP",
        source_ref="knowledge_space:42" if creator else f"42:admin:{user_id}",
        protected=True,
    )


@pytest.mark.asyncio
async def test_owner_handover_retires_old_creator_and_preserves_independent_owner():
    service, sources, projection, state, _ = _service()
    ctx = context()
    owner = ctx.grants[-1]
    old = source(sources, 2, creator=True)
    independent = sources.canonicalize_source(
        source_id=102,
        subject_type="user",
        subject_id="2",
        source_type="DIRECT",
    )
    owner = sources.add_source(owner, old).grant
    owner = sources.add_source(owner, independent).grant
    ctx = replace(ctx, grants=(*ctx.grants[:-1], owner))
    new = source(sources, 3, source_id=103)
    result = await service.reconcile_business_owner(ctx, source=new, idempotency_key="handover")
    assert result.grants[-1].sources == (independent, new)
    assert projection.plans[0].operation_type == "GRANT_MUTATION"
    assert state.prepared and state.finalized
    assert any(d.action == "DELETE" and d.user == "user:2" for d in projection.plans[0].deltas)
    assert any(d.action == "WRITE" and d.user == "user:3" for d in projection.plans[0].deltas)


@pytest.mark.asyncio
async def test_repeated_owner_reconcile_does_not_project_again():
    service, sources, projection, _, _ = _service()
    ctx = context()
    current = source(sources, 3)
    owner = sources.add_source(ctx.grants[-1], current).grant
    ctx = replace(ctx, grants=(*ctx.grants[:-1], owner))
    assert await service.reconcile_business_owner(ctx, source=current, idempotency_key="same") is None
    assert not projection.prepared


@pytest.mark.asyncio
async def test_pending_space_retires_responsible_owner_without_promoting_anyone():
    service, sources, _, _, _ = _service()
    ctx = context()
    owner = sources.add_source(ctx.grants[-1], source(sources, 3)).grant
    ctx = replace(ctx, grants=(*ctx.grants[:-1], owner))
    result = await service.reconcile_business_owner(ctx, source=None, idempotency_key="pending")
    assert not result.grants[-1].sources
    assert not result.grants[-1].active


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["ordinary_resource", "unprivileged"])
async def test_owner_reconcile_rejects_unverified_scope(invalid):
    service, sources, projection, _, _ = _service()
    ctx = context()
    if invalid == "ordinary_resource":
        ctx = replace(ctx, target=_context(capabilities=()).target)
    else:
        ctx = replace(ctx, system_authorized=False)
    with pytest.raises(PermissionInvalidResourceError):
        await service.reconcile_business_owner(ctx, source=source(sources, 3), idempotency_key="bad")
    assert not projection.prepared


@pytest.mark.asyncio
async def test_ordinary_mutation_still_cannot_remove_responsible_owner():
    service, sources, _, _, _ = _service()
    ctx = context()
    current = source(sources, 3)
    owner = sources.add_source(ctx.grants[-1], current).grant
    ctx = replace(ctx, grants=(*ctx.grants[:-1], owner))
    with pytest.raises(ProtectedAssignmentMutationError):
        await service.mutate(
            ctx,
            changes=(
                CanonicalGrantChange(
                    operation="REMOVE",
                    assignee_id=current.source_id,
                    expected_assignee_version=1,
                ),
            ),
            expected_resource_version=4,
            expected_catalog_release_id=12,
            idempotency_key="ordinary",
        )
