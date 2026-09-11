"""F048 permission-mode and resource-lifecycle contracts.

覆盖 AC: AC-45, AC-46, AC-47, AC-48, AC-49, AC-50, AC-51, AC-52,
AC-53, AC-54, AC-55, AC-56, AC-57, AC-150, AC-151, AC-152
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from bisheng.common.errcode.permission import (
    InvalidPermissionModeError,
    PermissionImpactExpiredError,
    PermissionProjectionFailedError,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.mode_service import (
    ModeContext,
    ModeService,
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
        self.fail = False

    async def prepare(self, plan):
        self.prepared.append(plan)
        return SimpleNamespace(id=88, status="PREPARED")

    async def abandon_prepared(self, plan, error):
        self.abandoned.append((plan, error))

    async def execute(self, plan):
        self.plans.append(plan)
        if self.fail:
            raise PermissionProjectionFailedError()
        return ProjectionOutcome(
            operation_id=88,
            target_version=plan.target_version,
            status="FINALIZED",
            request_checksum="8" * 64,
        )


class FakeModeState:
    def __init__(self) -> None:
        self.next_source_id = 100
        self.saved = []
        self.prepared = []
        self.finalized = []

    async def allocate_source_ids(self, count: int) -> tuple[int, ...]:
        values = tuple(range(self.next_source_id, self.next_source_id + count))
        self.next_source_id += count
        return values

    async def save_draft(self, draft) -> None:
        self.saved.append(draft)

    async def prepare(
        self,
        context,
        draft,
        grants,
        visibility,
        *,
        idempotency_key: str,
        operation_id: int,
    ) -> None:
        self.prepared.append((context, draft, grants, visibility, idempotency_key, operation_id))

    async def finalize(self, context, draft, grants, visibility, outcome) -> None:
        self.finalized.append((context, draft, grants, visibility, outcome))


class FakeEvents:
    def __init__(self) -> None:
        self.rows = []

    async def emit(self, name: str, fields: dict) -> None:
        self.rows.append((name, fields))


def _model(key: str, level: int) -> GrantModelSnapshot:
    return GrantModelSnapshot(
        model_key=key,
        active=True,
        action_codes=("download", "manage_permission"),
        derived_level=level,
    )


def _grant(key: str, *, grant_id: str | None = None) -> GrantSnapshot:
    return GrantSnapshot(
        grant_id=grant_id or f"g-{key}",
        tenant_id=7,
        resource_type="folder",
        resource_id="42",
        model=_model(key, 4 if key == "owner" else 2),
        active=False,
        sources=(),
    )


def _target(
    resource_type: str = "folder",
    *,
    parent: tuple[str, str] | None = ("knowledge_space", "10"),
) -> VerifiedPermissionTarget:
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=7,
        resource_type=resource_type,
        resource_id="42",
        resource_version=3,
        parent_type=parent[0] if parent else None,
        parent_id=parent[1] if parent else None,
        context_version="ctx-3",
    )


def _context(
    *,
    mode: str = "INHERIT",
    target: VerifiedPermissionTarget | None = None,
    local_grants: tuple[GrantSnapshot, ...] | None = None,
    inherited_grants: tuple[GrantSnapshot, ...] = (),
) -> ModeContext:
    resolved_local_grants = local_grants or (_grant("editor"), _grant("owner"))
    visible_sources = (
        VisibilityProjectionCompiler()
        .compile(
            tenant_id=7,
            grants=resolved_local_grants,
            existing_sources=(),
        )
        .active_sources
    )
    return ModeContext(
        target=target or _target(),
        mode=mode,
        current_catalog_release_id=12,
        store_id="store",
        model_id="model",
        operator_id=100,
        local_grants=resolved_local_grants,
        inherited_grants=inherited_grants,
        existing_visible_sources=visible_sources,
    )


def _service():
    source_service = GrantSourceService()
    projection = FakeProjection()
    state = FakeModeState()
    events = FakeEvents()
    service = ModeService(
        source_service=source_service,
        projection=projection,
        state=state,
        events=events,
    )
    return service, source_service, projection, state, events


def test_mode_defaults_and_fixed_top_level_resources() -> None:
    service, _, _, _, _ = _service()
    assert service.default_mode("folder", has_parent=True) == "INHERIT"
    assert service.default_mode("knowledge_file", has_parent=True) == "INHERIT"
    for resource_type in (
        "knowledge_space",
        "knowledge_library",
        "workflow",
        "assistant",
        "tool",
        "channel",
        "dashboard",
    ):
        assert service.default_mode(resource_type, has_parent=False) == "CUSTOM"
    with pytest.raises(InvalidPermissionModeError):
        service.default_mode("folder", has_parent=False)


@pytest.mark.asyncio
async def test_inherit_requires_parent_and_fixed_custom_types_reject_switch() -> None:
    service, _, _, _, _ = _service()
    with pytest.raises(InvalidPermissionModeError):
        await service.create_draft(
            _context(
                mode="CUSTOM",
                target=_target("folder", parent=None),
            ),
            target_mode="INHERIT",
        )
    for resource_type in ("knowledge_space", "knowledge_library", "dashboard"):
        with pytest.raises(InvalidPermissionModeError):
            await service.create_draft(
                _context(
                    mode="CUSTOM",
                    target=_target(resource_type, parent=None),
                ),
                target_mode="INHERIT",
            )


@pytest.mark.asyncio
async def test_inherit_to_custom_snapshots_ordinary_and_dedups_protected() -> None:
    service, sources, _, state, _ = _service()
    inherited_user = sources.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="300",
        source_type="DIRECT",
    )
    inherited_department = sources.canonicalize_source(
        source_id=2,
        subject_type="department",
        subject_id="17",
        include_children=True,
        source_type="DEPARTMENT",
    )
    inherited_owner = sources.add_source(_grant("owner"), inherited_user).grant
    inherited_editor = sources.add_source(
        _grant("editor"),
        inherited_department,
    ).grant
    protected = sources.canonicalize_source(
        source_id=3,
        subject_type="user",
        subject_id="300",
        source_type="CREATOR",
        source_ref="folder:42",
        protected=True,
    )
    local_owner = sources.add_source(_grant("owner"), protected).grant
    context = _context(
        local_grants=(_grant("editor"), local_owner),
        inherited_grants=(inherited_editor, inherited_owner),
    )
    draft = await service.create_draft(context, target_mode="CUSTOM")
    assert draft.target_mode == "CUSTOM"
    assert len(draft.snapshot_sources) == 1
    snapshot = draft.snapshot_sources[0]
    assert snapshot.subject_type == "department"
    assert snapshot.include_children is True
    assert snapshot.source_type == "SNAPSHOT_FROM_PARENT"
    assert snapshot.protected is False
    assert all(delta.phase == "STAGE" for delta in draft.staging_deltas)
    assert state.saved == [draft]


@pytest.mark.asyncio
async def test_apply_stages_visible_and_switches_mode_without_changing_parent() -> None:
    service, sources, projection, state, events = _service()
    inherited = sources.canonicalize_source(
        source_id=1,
        subject_type="department",
        subject_id="17",
        source_type="DEPARTMENT",
    )
    inherited_editor = sources.add_source(_grant("editor"), inherited).grant
    context = _context(inherited_grants=(inherited_editor,))
    draft = await service.create_draft(context, target_mode="CUSTOM")
    result = await service.apply(
        context,
        draft,
        expected_resource_version=3,
        expected_catalog_release_id=12,
        confirmed=True,
        idempotency_key="mode-custom",
    )
    assert result.applied is True
    assert result.mode == "CUSTOM"
    plan = projection.plans[0]
    commit = [row for row in plan.deltas if row.phase == "COMMIT"]
    assert {(row.action, row.relation) for row in commit} == {
        ("DELETE", "inherit_mode"),
        ("WRITE", "custom_mode"),
    }
    assert any(row.phase == "STAGE" and row.action == "WRITE" and row.relation == "visible" for row in plan.deltas)
    assert all(row.relation != "parent" for row in plan.deltas)
    assert len(state.prepared) == len(state.finalized) == 1
    assert events.rows[-1][0] == "permission_mode_switch"


@pytest.mark.asyncio
async def test_cancel_and_projection_failure_leave_old_mode_unchanged() -> None:
    service, _, projection, state, _ = _service()
    context = _context()
    draft = await service.create_draft(context, target_mode="CUSTOM")
    cancelled = await service.apply(
        context,
        draft,
        expected_resource_version=3,
        expected_catalog_release_id=12,
        confirmed=False,
        idempotency_key="cancelled",
    )
    assert cancelled.applied is False
    assert cancelled.mode == "INHERIT"
    assert projection.plans == []

    projection.fail = True
    with pytest.raises(PermissionProjectionFailedError):
        await service.apply(
            context,
            draft,
            expected_resource_version=3,
            expected_catalog_release_id=12,
            confirmed=True,
            idempotency_key="failed",
        )
    assert state.finalized == []
    assert context.mode == "INHERIT"


@pytest.mark.asyncio
async def test_stale_mode_draft_fails_before_projection() -> None:
    service, _, projection, _, _ = _service()
    context = _context()
    draft = await service.create_draft(context, target_mode="CUSTOM")
    changed_parent = replace(
        context,
        target=_target(parent=("knowledge_space", "11")),
    )
    with pytest.raises(PermissionImpactExpiredError):
        await service.apply(
            changed_parent,
            draft,
            expected_resource_version=3,
            expected_catalog_release_id=12,
            confirmed=True,
            idempotency_key="stale-parent",
        )
    assert projection.plans == []


@pytest.mark.asyncio
async def test_custom_to_inherit_retires_ordinary_but_preserves_protected() -> None:
    service, sources, projection, state, _ = _service()
    ordinary = sources.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="200",
        source_type="DIRECT",
    )
    protected = sources.canonicalize_source(
        source_id=2,
        subject_type="user",
        subject_id="201",
        source_type="CREATOR",
        source_ref="folder:42",
        protected=True,
    )
    owner = sources.add_source(_grant("owner"), protected).grant
    editor = sources.add_source(_grant("editor"), ordinary).grant
    context = _context(mode="CUSTOM", local_grants=(editor, owner))
    draft = await service.create_draft(context, target_mode="INHERIT")
    result = await service.apply(
        context,
        draft,
        expected_resource_version=3,
        expected_catalog_release_id=12,
        confirmed=True,
        idempotency_key="mode-inherit",
    )
    assert result.mode == "INHERIT"
    assert result.grants[0].sources == ()
    assert result.grants[1].sources[0].protected is True
    visible_deltas = [row for row in projection.plans[0].deltas if row.relation == "visible"]
    assert [(row.action, row.user) for row in visible_deltas] == [
        ("DELETE", "user:200"),
    ]
    prepared_visibility = state.prepared[0][3]
    assert [row.projected_subject for row in prepared_visibility.active_sources] == ["user:201"]
    assert [row.projected_subject for row in prepared_visibility.retired_sources] == ["user:200"]
    assert state.finalized


def test_move_copy_create_and_delete_lifecycle_plans() -> None:
    service, _, _, _, _ = _service()
    target = _target()
    move = service.move_plan(
        target,
        old_parent=("knowledge_space", "10"),
        new_parent=("folder", "20"),
        mode="CUSTOM",
        store_id="store",
        model_id="model",
        operator_id=100,
        idempotency_key="move",
    )
    assert {(row.action, row.relation, row.user) for row in move.deltas} == {
        ("DELETE", "permission_enabled", "user:*"),
        ("DELETE", "parent", "knowledge_space:10"),
        ("WRITE", "parent", "folder:20"),
        ("WRITE", "permission_enabled", "user:*"),
    }
    assert service.copy_mode("INHERIT") == ("INHERIT", False)
    assert service.copy_mode("CUSTOM") == ("CUSTOM", True)

    create_file = service.create_plan(
        _target("knowledge_file", parent=("folder", "20")),
        store_id="store",
        model_id="model",
        operator_id=100,
        idempotency_key="create-file",
        protected_deltas=(),
    )
    assert any(row.relation == "inherit_mode" for row in create_file.deltas)
    assert create_file.deltas[-1].relation == "permission_enabled"
    assert create_file.deltas[-1].phase == "COMMIT"

    copy_custom = service.create_plan(
        _target("knowledge_file", parent=("folder", "20")),
        store_id="store",
        model_id="model",
        operator_id=100,
        idempotency_key="copy-custom",
        protected_deltas=(),
        permission_mode="CUSTOM",
        operation_type="RESOURCE_COPY",
    )
    assert copy_custom.operation_type == "RESOURCE_COPY"
    assert any(row.relation == "custom_mode" for row in copy_custom.deltas)
    assert not any(row.relation == "inherit_mode" for row in copy_custom.deltas)

    delete = service.delete_plan(
        target,
        store_id="store",
        model_id="model",
        operator_id=100,
        idempotency_key="delete",
    )
    assert [(row.action, row.relation) for row in delete.deltas] == [("DELETE", "permission_enabled")]
