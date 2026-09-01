"""F048 grant-level and protected-assignment orchestration contracts.

覆盖 AC: AC-15, AC-36, AC-37, AC-38, AC-39, AC-40, AC-41, AC-42,
AC-43, AC-44, AC-164, AC-166, AC-167, AC-170, AC-157
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from bisheng.common.errcode.permission import (
    GrantLevelForbiddenError,
    PermissionModelStateConflictError,
    PermissionVersionConflictError,
    ProtectedAssignmentMutationError,
)
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
from bisheng.permission.domain.services.projection_service import ProjectionOutcome
from bisheng.permission.domain.services.visibility_projection_service import (
    VisibilityProjectionCompiler,
)


class FakeProjection:
    def __init__(self) -> None:
        self.plans = []
        self.prepared = []
        self.abandoned = []

    async def prepare(self, plan):
        self.prepared.append(plan)
        return SimpleNamespace(id=99, status="PREPARED")

    async def abandon_prepared(self, plan, error):
        self.abandoned.append((plan, error))

    async def execute(self, plan):
        self.plans.append(plan)
        return ProjectionOutcome(
            operation_id=99,
            target_version=plan.target_version,
            status="FINALIZED",
            request_checksum="f" * 64,
        )


class FakeGrantState:
    def __init__(self) -> None:
        self.prepared = []
        self.finalized = []

    async def prepare(
        self,
        context,
        grants,
        visibility,
        *,
        idempotency_key: str,
        operation_id: int,
    ) -> None:
        self.prepared.append((context, grants, visibility, idempotency_key, operation_id))

    async def finalize(self, context, grants, visibility, outcome) -> None:
        self.finalized.append((context, grants, visibility, outcome))


class FakeEvents:
    def __init__(self) -> None:
        self.rows = []

    async def emit(self, name: str, fields: dict) -> None:
        self.rows.append((name, fields))


def _model(
    key: str,
    level: int,
    *actions: str,
    allow_same_level: bool = False,
    active: bool = True,
) -> GrantModelSnapshot:
    return GrantModelSnapshot(
        model_key=key,
        active=active,
        action_codes=tuple(actions),
        derived_level=level,
        allow_same_level=allow_same_level,
    )


def _grant(model: GrantModelSnapshot, grant_id: str | None = None) -> GrantSnapshot:
    return GrantSnapshot(
        grant_id=grant_id or f"g-{model.model_key}",
        tenant_id=7,
        resource_type="workflow",
        resource_id="42",
        model=model,
        active=False,
        sources=(),
    )


def _context(
    *,
    capabilities: tuple[GrantCapability, ...],
    grants: tuple[GrantSnapshot, ...] | None = None,
    catalog_release_id: int = 12,
    system_authorized: bool = False,
) -> GrantMutationContext:
    models = (
        _model("viewer", 1, "download"),
        _model("editor", 2, "download", "edit"),
        _model(
            "manager",
            3,
            "download",
            "edit",
            "manage_permission",
        ),
        _model(
            "owner",
            4,
            "download",
            "edit",
            "manage_permission",
            "delete",
            allow_same_level=True,
        ),
    )
    return GrantMutationContext(
        target=VerifiedPermissionTarget.from_business_service(
            tenant_id=7,
            resource_type="workflow",
            resource_id="42",
            resource_version=4,
            context_version="ctx-4",
        ),
        current_catalog_release_id=catalog_release_id,
        store_id="store",
        model_id="model",
        operator_id=100,
        mode="CUSTOM",
        system_authorized=system_authorized,
        capabilities=capabilities,
        models=models,
        grants=grants or tuple(_grant(model) for model in models),
        existing_visible_sources=(),
    )


def _service():
    projection = FakeProjection()
    state = FakeGrantState()
    events = FakeEvents()
    source_service = GrantSourceService()
    service = GrantService(
        source_service=source_service,
        projection=projection,
        state=state,
        events=events,
    )
    return service, source_service, projection, state, events


def test_grantable_levels_are_computed_per_source_model() -> None:
    service, _, _, _, _ = _service()
    no_manage = GrantCapability(
        model=_model("high-no-manage", 4, "delete"),
        source_key="high",
    )
    low_manage = GrantCapability(
        model=_model("low-manage", 2, "manage_permission"),
        source_key="low",
    )
    context = _context(capabilities=(no_manage, low_manage))
    assert [model.model_key for model in service.grantable_models(context)] == ["viewer"]
    with pytest.raises(GrantLevelForbiddenError):
        service.require_grantable_model(context, "manager")


def test_same_level_policy_is_independent_and_union_does_not_cross_splice() -> None:
    service, _, _, _, _ = _service()
    strict_manager = GrantCapability(
        model=_model(
            "strict",
            3,
            "manage_permission",
            allow_same_level=False,
        ),
        source_key="strict-source",
    )
    same_level_editor = GrantCapability(
        model=_model(
            "same",
            2,
            "manage_permission",
            allow_same_level=True,
        ),
        source_key="same-source",
    )
    context = _context(capabilities=(strict_manager, same_level_editor))
    assert [model.model_key for model in service.grantable_models(context)] == [
        "viewer",
        "editor",
    ]
    with pytest.raises(GrantLevelForbiddenError):
        service.require_grantable_model(context, "manager")


@pytest.mark.asyncio
async def test_no_manage_source_rejects_roster_and_mutation() -> None:
    service, source_service, _, _, _ = _service()
    context = _context(
        capabilities=(
            GrantCapability(
                model=_model("editor", 2, "edit"),
                source_key="editor-source",
            ),
        )
    )
    with pytest.raises(GrantLevelForbiddenError):
        service.assert_roster_access(context)
    source = source_service.canonicalize_source(
        source_id=20,
        subject_type="user",
        subject_id="200",
        source_type="DIRECT",
    )
    with pytest.raises(GrantLevelForbiddenError):
        await service.mutate(
            context,
            changes=(
                CanonicalGrantChange(
                    operation="ADD",
                    model_key="viewer",
                    source=source,
                ),
            ),
            expected_resource_version=4,
            expected_catalog_release_id=12,
            idempotency_key="no-manage",
        )


@pytest.mark.asyncio
async def test_stale_catalog_resource_and_assignee_versions_are_rejected() -> None:
    service, source_service, _, _, _ = _service()
    capability = GrantCapability(
        model=_model("owner", 4, "manage_permission", allow_same_level=True),
        source_key="owner-source",
    )
    context = _context(capabilities=(capability,))
    source = source_service.canonicalize_source(
        source_id=20,
        subject_type="user",
        subject_id="200",
        source_type="DIRECT",
    )
    change = CanonicalGrantChange(
        operation="ADD",
        model_key="viewer",
        source=source,
    )
    with pytest.raises(PermissionVersionConflictError):
        await service.mutate(
            context,
            changes=(change,),
            expected_resource_version=3,
            expected_catalog_release_id=12,
            idempotency_key="stale-resource",
        )
    with pytest.raises(PermissionVersionConflictError):
        await service.mutate(
            context,
            changes=(change,),
            expected_resource_version=4,
            expected_catalog_release_id=11,
            idempotency_key="stale-catalog",
        )

    seeded = source_service.add_source(context.grants[0], source).grant
    seeded_context = replace(
        context,
        grants=(seeded, *context.grants[1:]),
    )
    with pytest.raises(PermissionVersionConflictError):
        await service.mutate(
            seeded_context,
            changes=(
                CanonicalGrantChange(
                    operation="REMOVE",
                    assignee_id=20,
                    expected_assignee_version=999,
                ),
            ),
            expected_resource_version=4,
            expected_catalog_release_id=12,
            idempotency_key="stale-assignee",
        )


@pytest.mark.asyncio
async def test_protected_assignment_cannot_be_removed_or_downgraded() -> None:
    service, source_service, _, _, _ = _service()
    capability = GrantCapability(
        model=_model("owner", 4, "manage_permission", allow_same_level=True),
        source_key="owner-source",
    )
    context = _context(capabilities=(capability,))
    protected = source_service.canonicalize_source(
        source_id=30,
        subject_type="user",
        subject_id="300",
        source_type="CREATOR",
        source_ref="workflow:42",
        protected=True,
    )
    owner_index = 3
    owner = source_service.add_source(
        context.grants[owner_index],
        protected,
    ).grant
    context = replace(
        context,
        grants=(*context.grants[:owner_index], owner),
    )
    for change in (
        CanonicalGrantChange(
            operation="REMOVE",
            assignee_id=30,
            expected_assignee_version=1,
        ),
        CanonicalGrantChange(
            operation="MOVE",
            assignee_id=30,
            expected_assignee_version=1,
            target_model_key="viewer",
        ),
    ):
        with pytest.raises(ProtectedAssignmentMutationError):
            await service.mutate(
                context,
                changes=(change,),
                expected_resource_version=4,
                expected_catalog_release_id=12,
                idempotency_key=f"protected-{change.operation}",
            )


@pytest.mark.asyncio
async def test_multiple_owner_sources_are_allowed_and_projection_finalizes() -> None:
    service, source_service, projection, state, events = _service()
    capability = GrantCapability(
        model=_model("owner", 4, "manage_permission", allow_same_level=True),
        source_key="owner-source",
    )
    context = _context(capabilities=(capability,))
    creator = source_service.canonicalize_source(
        source_id=30,
        subject_type="user",
        subject_id="300",
        source_type="CREATOR",
        source_ref="workflow:42",
        protected=True,
    )
    owner = source_service.add_source(context.grants[3], creator).grant
    context = replace(context, grants=(*context.grants[:3], owner))
    ordinary_owner = source_service.canonicalize_source(
        source_id=31,
        subject_type="user",
        subject_id="301",
        source_type="DIRECT",
    )
    result = await service.mutate(
        context,
        changes=(
            CanonicalGrantChange(
                operation="ADD",
                model_key="owner",
                source=ordinary_owner,
            ),
        ),
        expected_resource_version=4,
        expected_catalog_release_id=12,
        idempotency_key="add-second-owner",
    )
    assert len(result.grants[3].sources) == 2
    assert sum(row.protected for row in result.grants[3].sources) == 1
    assert result.resource_version == 5
    assert len(projection.plans) == 1
    assert len(state.prepared) == len(state.finalized) == 1
    assert events.rows[-1][0] == "permission_grant_mutation"


def test_inactive_target_model_is_not_grantable() -> None:
    service, _, _, _, _ = _service()
    capability = GrantCapability(
        model=_model("owner", 4, "manage_permission", allow_same_level=True),
        source_key="owner-source",
    )
    context = _context(capabilities=(capability,))
    models = tuple(replace(model, active=False) if model.model_key == "viewer" else model for model in context.models)
    context = replace(context, models=models)
    with pytest.raises(PermissionModelStateConflictError):
        service.require_grantable_model(context, "viewer")


@pytest.mark.asyncio
async def test_add_commits_action_and_single_slot_visible_in_one_operation() -> None:
    service, source_service, projection, state, _ = _service()
    capability = GrantCapability(
        model=_model("owner", 4, "manage_permission", allow_same_level=True),
        source_key="owner-source",
    )
    context = _context(capabilities=(capability,))
    source = source_service.canonicalize_source(
        source_id=40,
        subject_type="user",
        subject_id="400",
        source_type="DIRECT",
    )

    await service.mutate(
        context,
        changes=(CanonicalGrantChange(operation="ADD", model_key="viewer", source=source),),
        expected_resource_version=4,
        expected_catalog_release_id=12,
        idempotency_key="add-visible",
    )

    plan = projection.plans[0]
    assert {row.relation for row in plan.deltas} >= {
        "ordinary_assignee",
        "visible",
    }
    assert all("slot" not in row.relation and not row.relation.endswith(("_a", "_b")) for row in plan.deltas)
    prepared_visibility = state.prepared[0][2]
    assert [row.model_key for row in prepared_visibility.active_sources] == ["viewer"]


@pytest.mark.asyncio
async def test_inactive_source_model_allows_precise_remove_and_visible_revoke() -> None:
    service, source_service, projection, state, _ = _service()
    inactive_viewer = _model("viewer", 1, "download", active=False)
    source = source_service.canonicalize_source(
        source_id=41,
        subject_type="user",
        subject_id="401",
        source_type="DIRECT",
    )
    seeded = source_service.add_source(
        _grant(replace(inactive_viewer, active=True)),
        source,
    ).grant
    seeded = replace(seeded, model=inactive_viewer)
    base = _context(
        capabilities=(
            GrantCapability(
                model=_model("owner", 4, "manage_permission", allow_same_level=True),
                source_key="owner-source",
            ),
        )
    )
    models = (inactive_viewer, *base.models[1:])
    grants = (seeded, *base.grants[1:])
    existing = VisibilityProjectionCompiler().compile(
        tenant_id=7,
        grants=grants,
        existing_sources=(),
    ).active_sources
    context = replace(
        base,
        models=models,
        grants=grants,
        existing_visible_sources=existing,
    )

    await service.mutate(
        context,
        changes=(
            CanonicalGrantChange(
                operation="REMOVE",
                assignee_id=41,
                expected_assignee_version=1,
            ),
        ),
        expected_resource_version=4,
        expected_catalog_release_id=12,
        idempotency_key="remove-inactive-visible",
    )

    assert {row.relation for row in projection.plans[0].deltas} >= {
        "ordinary_assignee",
        "visible",
    }
    prepared_visibility = state.prepared[0][2]
    assert prepared_visibility.active_sources == ()
    assert len(prepared_visibility.retired_sources) == 1


@pytest.mark.asyncio
async def test_move_freezes_action_and_single_slot_contribution_in_same_operation() -> None:
    service, source_service, projection, state, _ = _service()
    source = source_service.canonicalize_source(
        source_id=42,
        subject_type="user",
        subject_id="402",
        source_type="DIRECT",
    )
    base = _context(
        capabilities=(
            GrantCapability(
                model=_model("owner", 4, "manage_permission", allow_same_level=True),
                source_key="owner-source",
            ),
        )
    )
    viewer = source_service.add_source(base.grants[0], source).grant
    grants = (viewer, *base.grants[1:])
    existing = VisibilityProjectionCompiler().compile(
        tenant_id=7,
        grants=grants,
        existing_sources=(),
    ).active_sources
    context = replace(base, grants=grants, existing_visible_sources=existing)

    await service.mutate(
        context,
        changes=(
            CanonicalGrantChange(
                operation="MOVE",
                assignee_id=42,
                expected_assignee_version=1,
                target_model_key="editor",
            ),
        ),
        expected_resource_version=4,
        expected_catalog_release_id=12,
        idempotency_key="move-visible",
    )

    assert projection.plans[0].operation_type == "GRANT_MUTATION"
    assert "ordinary_assignee" in {row.relation for row in projection.plans[0].deltas}
    visibility = state.prepared[0][2]
    assert [row.model_key for row in visibility.active_sources] == ["editor"]
    assert [row.model_key for row in visibility.retired_sources] == ["viewer"]
    assert visibility.deltas == ()
