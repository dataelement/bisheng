"""Self-exit operates on current canonical permission sources."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import (
    PermissionDeniedError,
    PermissionPublishNotReadyError,
    PermissionVersionConflictError,
)
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_service import GrantService
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.permission.domain.services.projection_service import ProjectionOutcome


def source(n=1, kind="user", subject="9", provenance="DIRECT", **kwargs):
    return GrantSourceService().canonicalize_source(
        source_id=n, subject_type=kind, subject_id=subject, source_type=provenance, source_ref="local-source", **kwargs
    )


class State:
    def __init__(self, grants, model):
        self.grants, self.version, self.mode = grants, 3, "CUSTOM"
        self.prepared, self.finalized, self.prepare_error = [], [], None
        self.catalog = SimpleNamespace(
            release_id=12,
            store_id="store",
            model_id="model",
            models=(SimpleNamespace(snapshot=model),),
            action_resource_scopes=(("download", ("knowledge_space",)),),
        )

    async def current_catalog(self):
        return self.catalog

    async def mode_for_target(self, target):
        return SimpleNamespace(
            version=self.version, parent_type=None, parent_id=None, projection_state="CURRENT", mode=self.mode
        )

    async def load_grants(self, **kwargs):
        return self.grants

    async def load_visible_sources(self, **kwargs):
        return ()

    async def prepare(self, context, grants, visibility, **kwargs):
        if self.prepare_error:
            raise self.prepare_error
        self.prepared.append((context, grants, kwargs))

    async def finalize(self, context, grants, visibility, outcome):
        self.grants, self.version = grants, outcome.target_version
        self.finalized.append((context, grants, visibility))


class Projection:
    def __init__(self):
        self.plans, self.executed, self.abandoned = [], [], []

    async def prepare(self, plan):
        self.plans.append(plan)
        return SimpleNamespace(id=99, status="PREPARED")

    async def execute(self, plan):
        self.executed.append(plan)
        return ProjectionOutcome(
            operation_id=99, target_version=plan.target_version, status="FINALIZED", request_checksum="f" * 64
        )

    async def abandon_prepared(self, plan, error):
        self.abandoned.append((plan, error))


def fixture(rows=(), inactive_model=False):
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=7, resource_type="knowledge_space", resource_id="space", resource_version=3, context_version="test"
    )
    model = GrantModelSnapshot("viewer", not inactive_model, ("download",), derived_level=1)
    state = State((GrantSnapshot("grant", 7, "knowledge_space", "space", model, True, tuple(rows)),), model)
    projection = Projection()
    runtime = F048PermissionRuntime(
        client=SimpleNamespace(store_id="store", model_id="model"),
        state=state,
        marker=None,
        decision=None,
        projection=projection,
        sources=GrantSourceService(),
        owner=None,
        grants=GrantService(source_service=GrantSourceService(), projection=projection, state=state),
        modes=None,
        explain=None,
    )
    runtime._grant_capabilities = AsyncMock(return_value=())
    return runtime, PermissionActor(user_id=9, current_tenant_id=7), target, state, projection


async def status(runtime, actor, target, subjects=frozenset()):
    return await runtime.personal_space_exit_status(actor=actor, target=target, actor_projected_subjects=subjects)


async def execute(runtime, actor, target, subjects=frozenset()):
    return await runtime.exit_personal_space(
        actor=actor, target=target, actor_projected_subjects=subjects, idempotency_key="leave-1"
    )


async def test_personal_grant_without_membership_exits_and_retry_is_noop():
    runtime, actor, target, state, projection = fixture((source(),))
    assert (await status(runtime, actor, target)).can_exit is True
    result = await execute(runtime, actor, target)
    assert result.resource_version == 4
    assert state.grants[0].sources == () and state.grants[0].active is False
    assert projection.executed[0].idempotency_key == "leave-1"
    assert any(d.user == "user:9" and d.action == "DELETE" for d in projection.executed[0].deltas)
    fresh = target.model_copy(update={"resource_version": 4})
    assert (await status(runtime, actor, fresh)).reason == "no_personal_grant"
    assert await execute(runtime, actor, fresh) is None
    assert len(projection.executed) == 1


@pytest.mark.parametrize(
    "kind,relation",
    [
        ("department", "member"),
        ("department", "subtree_member"),
        ("user_group", "member"),
        ("user_group", "admin"),
        ("tenant", "member"),
    ],
)
@pytest.mark.parametrize("mixed", [False, True])
async def test_effective_organization_source_blocks_exit(kind, relation, mixed):
    row = source(
        2,
        kind,
        "17",
        {"department": "DEPARTMENT", "user_group": "USER_GROUP", "tenant": "TENANT"}[kind],
        userset_relation=relation,
        include_children=relation == "subtree_member",
    )
    runtime, actor, target, state, projection = fixture((source(), row) if mixed else (row,))
    subjects = frozenset({row.projected_subject})
    result = await status(runtime, actor, target, subjects)
    assert result.can_exit is False and result.reason == "organization_grant"
    with pytest.raises(PermissionDeniedError):
        await execute(runtime, actor, target, subjects)
    assert not state.prepared and not projection.plans


@pytest.mark.parametrize("row", [source(protected=True), source(provenance="CREATOR")])
async def test_creator_and_protected_source_block_exit(row):
    runtime, actor, target, _state, projection = fixture((source(2), row))
    assert (await status(runtime, actor, target)).reason == "creator"
    with pytest.raises(PermissionDeniedError):
        await execute(runtime, actor, target)
    assert not projection.plans


async def test_removes_all_local_personal_models_preserving_other_subjects():
    other = source(2, subject="10")
    unrelated_org = source(3, "department", "17", "DEPARTMENT")
    runtime, actor, target, state, projection = fixture((source(), other, unrelated_org))
    old_model = GrantModelSnapshot("old", False, ("download",), derived_level=1)
    rows = (source(4, provenance="SPACE_MEMBERSHIP"), source(5, provenance="SNAPSHOT_FROM_PARENT"))
    state.grants += (GrantSnapshot("old-grant", 7, "knowledge_space", "space", old_model, True, rows),)
    state.catalog.models += (SimpleNamespace(snapshot=old_model),)
    assert (await status(runtime, actor, target)).can_exit is True
    await execute(runtime, actor, target)
    assert state.grants[0].sources == (other, unrelated_org)
    assert state.grants[1].sources == ()
    assert state.prepared[0][0].current_catalog_release_id == 12
    assert projection.executed[0].expected_version == 3


@pytest.mark.parametrize("provenance", ["OTHER", "CHANNEL_MEMBERSHIP", "DEPARTMENT"])
async def test_foreign_personal_provenance_blocks_without_modification(provenance):
    foreign = (
        source(2, provenance=provenance) if provenance != "DEPARTMENT" else replace(source(2), source_type="DEPARTMENT")
    )
    runtime, actor, target, state, projection = fixture((source(), foreign))
    assert (await status(runtime, actor, target)).reason == "no_personal_grant"
    with pytest.raises(PermissionDeniedError):
        await execute(runtime, actor, target)
    assert not projection.plans and state.grants[0].sources == (source(), foreign)


async def test_inactive_grants_and_sources_ignored_but_disabled_model_keeps_effect():
    org = source(2, "department", "17", "DEPARTMENT")
    runtime, actor, target, state, _ = fixture((source(), replace(org, active=False)), inactive_model=True)
    inactive_model = replace(state.grants[0].model, model_key="inactive-model")
    state.grants += (replace(state.grants[0], grant_id="inactive", model=inactive_model, active=False, sources=(org,)),)
    state.catalog.models += (SimpleNamespace(snapshot=inactive_model),)
    assert (await status(runtime, actor, target, frozenset({org.projected_subject}))).can_exit is True
    await execute(runtime, actor, target, frozenset({org.projected_subject}))
    assert not state.grants[0].sources


async def test_disabled_model_organization_source_still_prevents_exit():
    org = source(2, "department", "17", "DEPARTMENT")
    runtime, actor, target, state, projection = fixture((source(), org), inactive_model=True)
    result = await status(runtime, actor, target, frozenset({org.projected_subject}))
    assert result.reason == "organization_grant" and result.can_exit is False
    with pytest.raises(PermissionDeniedError):
        await execute(runtime, actor, target, frozenset({org.projected_subject}))
    assert not state.prepared and not projection.plans


async def test_missing_personal_source_is_an_idempotent_noop():
    runtime, actor, target, state, projection = fixture((source(subject="10"),))
    assert (await status(runtime, actor, target)).reason == "no_personal_grant"
    assert await execute(runtime, actor, target) is None
    assert not state.prepared and not projection.plans


async def test_stale_target_fails_both_entrypoints_before_mutation():
    runtime, actor, target, state, projection = fixture((source(),))
    state.version = 4
    for operation in (status, execute):
        with pytest.raises(PermissionPublishNotReadyError):
            await operation(runtime, actor, target)
    assert not state.prepared and not projection.plans


@pytest.mark.parametrize(
    "actor,target_type",
    [
        (PermissionActor(subject_type="service_account", subject_id=9, tenant_id=7), "knowledge_space"),
        (PermissionActor(subject_id=9, tenant_id=8, super_admin=True), "knowledge_space"),
        (PermissionActor(subject_id=9, tenant_id=7), "knowledge_file"),
    ],
)
async def test_identity_tenant_and_resource_fences(actor, target_type):
    runtime, _, target, _, projection = fixture((source(),))
    target = target.model_copy(update={"resource_type": target_type})
    for operation in (status, execute):
        with pytest.raises(PermissionDeniedError):
            await operation(runtime, actor, target)
    assert not projection.plans


@pytest.mark.parametrize("mode", ["INHERIT", "READ_ONLY"])
async def test_unsupported_mode_fails_both_entrypoints(mode):
    runtime, actor, target, state, _ = fixture((source(),))
    state.mode = mode
    for operation in (status, execute):
        with pytest.raises(PermissionPublishNotReadyError):
            await operation(runtime, actor, target)


async def test_over_fifty_sources_fails_without_partial_mutation():
    runtime, actor, target, state, projection = fixture(
        tuple(source(i, provenance="SPACE_MEMBERSHIP") for i in range(1, 52))
    )
    for operation in (status, execute):
        with pytest.raises(PermissionPublishNotReadyError):
            await operation(runtime, actor, target)
    assert not state.prepared and not projection.plans


async def test_execution_rechecks_current_organization_sources_after_status():
    runtime, actor, target, state, projection = fixture((source(),))
    assert (await status(runtime, actor, target)).can_exit is True
    org = source(2, "department", "17", "DEPARTMENT")
    state.grants = (replace(state.grants[0], sources=(*state.grants[0].sources, org)),)
    with pytest.raises(PermissionDeniedError):
        await execute(runtime, actor, target, frozenset({org.projected_subject}))
    assert not projection.plans


async def test_cas_conflict_abandons_projection_and_can_retry():
    runtime, actor, target, state, projection = fixture((source(),))
    state.prepare_error = PermissionVersionConflictError()
    with pytest.raises(PermissionVersionConflictError):
        await execute(runtime, actor, target)
    assert state.grants[0].sources == (source(),)
    assert not projection.executed and len(projection.abandoned) == 1
    state.prepare_error = None
    await execute(runtime, actor, target)
    assert not state.grants[0].sources
