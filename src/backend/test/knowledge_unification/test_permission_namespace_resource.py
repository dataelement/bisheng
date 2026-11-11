"""T995: namespace plans from complete native Mode/Grant/Source facts."""

from dataclasses import asdict, replace

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.domain.services.grant_source_service import GrantSourceService
from bisheng.permission.domain.services.visibility_projection_service import VisibilityProjectionCompiler
from bisheng.permission.migration import f118_plan as plans
from bisheng.permission.migration import f118_verify as verify
from test.knowledge_unification import test_perm_migration_snapshot as native
from test.knowledge_unification.test_perm_migration import resource
from test.knowledge_unification.test_perm_migration_snapshot import storage as storage
from test.knowledge_unification.test_permission_floor_retirement_signing import legacy_catalog
from test.knowledge_unification.test_permission_namespace_catalog import MAPPING, build


def source(ident, *, department=False, protected=False):
    value = GrantSourceService().canonicalize_source(
        source_id=ident,
        subject_type="department" if department else "user",
        subject_id="19" if department else "7",
        source_type="DEPARTMENT" if department else "CREATOR" if protected else "OTHER" if ident == 3 else "DIRECT",
        include_children=department,
        protected=protected,
        source_ref="creator:knowledge_library:40" if protected else "original-source",
    )
    facts = asdict(value)
    del facts["active"]
    return plans.PermissionAssigneeBaseline(
        id=facts.pop("source_id"),
        grant_id=11,
        tenant_id=101,
        state="ACTIVE",
        **facts,
    )


def original_resource(before, *, resource_type="knowledge_library", model_key="mixed-use", retired=True):
    value = resource(plans, before, resource_type=resource_type, model_key=model_key)
    assignees = (source(1), source(2, protected=True), replace(source(3), state="INACTIVE"), source(4, department=True))
    assignees = tuple(replace(row, version=3) for row in assignees)
    value = replace(
        value,
        mode=replace(value.mode, version=5, operation_id=19),
        grants=tuple(replace(row, version=4) for row in value.grants),
        assignees=assignees,
    )
    buckets = {11: tuple(row.to_source_record() for row in assignees)}
    grants = plans._grants(
        value,
        {row.model_key: row for row in before.models},
        {row.code: row.resource_types for row in before.actions},
        buckets,
    )
    active = VisibilityProjectionCompiler().compile(tenant_id=101, grants=grants, existing_sources=()).active_sources
    records = list(active)
    if retired:
        records.append(
            VisibilityProjectionCompiler._compile_source(101, grants[0], buckets[11][2]).model_copy(
                update={"state": "RETIRED"}
            )
        )
    return replace(
        value,
        visible_sources=tuple(
            plans.PermissionVisibleSourceBaseline(
                index,
                row.model_copy(
                    update={"source_version": 0 if index == 1 else 9, "operation_id": 19, "migration_item_id": 23}
                ),
            )
            for index, row in enumerate(records, 1)
        ),
    )


def mapped(before):
    return build(before, namespace_type_mappings=MAPPING)


def target(before, **changes):
    return replace(before.mode, **changes)


def compile_resource(catalog, before, mode):
    return plans.build_resource_retirement_plan(catalog_plan=catalog, before=before, namespace_target=mode)


def test_original_unmapped_resource_keeps_its_fixed_prechange_checksum():
    catalog = legacy_catalog()
    before = original_resource(catalog)
    result = plans.build_resource_retirement_plan(catalog_plan=build(catalog), before=before)
    assert result.checksum == "918cb725064907eb35182d2ac84d0d7fc2477b58efa33a55d1f7f0185498126a"
    assert verify.verify_resource_retirement(plan=result, actual=before).complete


@pytest.fixture
async def original(storage, monkeypatch):
    catalog = legacy_catalog()
    frozen = original_resource(catalog)
    monkeypatch.setattr(native, "baseline", lambda _module: catalog)
    monkeypatch.setattr(native, "resource", lambda _module: frozen)
    async with AsyncSession(storage) as session, session.begin():
        await native.seed_catalog(session)
        session.add(
            native.PermissionProjectionOperation(
                id=19,
                tenant_id=101,
                idempotency_key="original",
                request_checksum="a" * 64,
                operation_type="resource",
                scope_type="resource",
                scope_key="knowledge_library:40",
                expected_version=4,
                target_version=5,
                store_id="original-store",
                model_id="original-model",
                status="FINALIZED",
                before_checksum="b" * 64,
                after_checksum="c" * 64,
                operator_id=7,
            )
        )
        await native.seed_rows(session)
    async with AsyncSession(storage) as session, session.begin():
        repo = PermissionMigrationSnapshotRepository()
        acquired = await repo.aload_catalog_baseline(session, environment="test")
        modes = await repo.alist_resource_modes(session)
        value = plans.PermissionResourceBaseline(
            101,
            "knowledge_library",
            "40",
            modes[0],
            await repo.alist_grants(session),
            await repo.alist_assignees(session),
            await repo.alist_visible_sources(session),
        )
        assert value == frozen and acquired == catalog
    return storage, acquired, value


async def test_native_root_changes_only_explicit_namespace_and_compiler_tuple_identity(original):
    engine, before_catalog, before = original
    catalog = mapped(before_catalog)
    statements = []

    def capture(_c, _cu, sql, _p, _ctx, _many):
        statements.append(sql)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        mode = target(before, resource_type="knowledge_space")
        result = compile_resource(catalog, before, mode)
        assert result.namespace_target is mode
        after = result.after
        assert after.mode == mode and after.resource_type == "knowledge_space"
        assert after.assignees is before.assignees
        assert after.grants == tuple(replace(row, resource_type="knowledge_space") for row in before.grants)
        assert result.after_grants[0].resource_type == "knowledge_space"
        assert result.after_grants[0].sources == tuple(row.to_source_record() for row in before.assignees)
        assert result.visible_subjects == ("department:19#subtree_member", "user:7")
        assert len(result.visibility_deltas) == 4
        assert {row.action for row in result.visibility_deltas} == {"DELETE", "WRITE"}
        for old, new in zip(before.visible_sources, after.visible_sources, strict=True):
            assert old.id == new.id and old.source.contribution_fingerprint == new.source.contribution_fingerprint
            assert new.source.tuple_fingerprint != old.source.tuple_fingerprint
            assert new.source == old.source.model_copy(
                update={"resource_type": "knowledge_space", "tuple_fingerprint": new.source.tuple_fingerprint}
            )
        assert verify.verify_resource_retirement(plan=result, actual=after).complete
        with pytest.raises(PermissionMigrationBlockedError):
            verify.verify_resource_retirement(plan=result, actual=before)
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert not statements


async def test_qa_and_existing_space_require_explicit_unchanged_mode_and_keep_all_rows(original):
    _, before_catalog, qa = original
    catalog = mapped(before_catalog)
    qa_plan = compile_resource(catalog, qa, qa.mode)
    assert qa_plan.after == qa and qa_plan.after.assignees is qa.assignees
    assert not qa_plan.visibility_deltas
    space = original_resource(before_catalog, resource_type="knowledge_space", model_key="owner")
    current = compile_resource(catalog, space, space.mode)
    assert current.after == space and not current.visibility_deltas
    assert verify.verify_resource_retirement(plan=current, actual=space).complete
    for value in (qa, space):
        with pytest.raises(PermissionMigrationBlockedError):
            plans.build_resource_retirement_plan(catalog_plan=catalog, before=value)


@pytest.mark.parametrize("kind", ["folder", "knowledge_file"])
def test_child_parent_namespace_changes_without_changing_its_own_identity_or_file_actions(kind):
    before_catalog = legacy_catalog()
    before = original_resource(before_catalog, resource_type=kind)
    before = replace(before, mode=target(before, parent_type="knowledge_library", parent_id="40"))
    mode = target(before, parent_type="knowledge_space")
    result = compile_resource(mapped(before_catalog), before, mode)
    assert result.after.resource_type == kind and result.after.mode == mode
    assert result.after.grants == before.grants and result.after.assignees == before.assignees
    assert result.after.visible_sources == before.visible_sources and not result.visibility_deltas
    assert result.after_grants[0].model.action_codes == ("download",)
    assert verify.verify_resource_retirement(plan=result, actual=result.after).complete


@pytest.mark.parametrize("inactive", [False, True])
def test_existing_space_requires_original_active_proof_before_accepting_visibility_provenance(inactive):
    before_catalog = legacy_catalog()
    # Old use covers Library but never SPACE. A legacy malformed active grant
    # with zero applicable old actions must not gain visibility from C4 metadata.
    before = resource(plans, before_catalog, resource_type="knowledge_space", model_key="pure-use")
    if inactive:
        before = replace(
            before,
            grants=tuple(replace(row, state="INACTIVE") for row in before.grants),
            visible_sources=tuple(
                replace(row, source=row.source.model_copy(update={"state": "RETIRED"}))
                for row in before.visible_sources
            ),
        )
    if inactive:
        with pytest.raises(PermissionMigrationBlockedError):
            compile_resource(mapped(before_catalog), before, before.mode)
    else:
        plan = compile_resource(mapped(before_catalog), before, before.mode)
        assert plan.after == before and not plan.visibility_deltas
        assert plan.after_grants[0].model.action_codes == ()
        assert plan.after_grants[0].model.derived_level == next(
            m.derived_level for m in before_catalog.models if m.model_key == "pure-use"
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": 202},
        {"id": 99},
        {"resource_id": "41"},
        {"mode": "INHERIT"},
        {"version": 6},
        {"version": 5.0},
        {"projection_state": "PENDING"},
        {"operation_id": 20},
        {"resource_type": "folder"},
        {"parent_type": "folder", "parent_id": "40"},
    ],
)
async def test_target_cannot_change_any_original_mode_fact_outside_approved_namespace(original, changes):
    _, catalog, before = original
    with pytest.raises(PermissionMigrationBlockedError):
        compile_resource(mapped(catalog), before, target(before, **changes))


@pytest.mark.parametrize("change", ["parent_id", "clear_parent", "reverse"])
def test_parent_and_resource_reverse_or_owner_layer_changes_are_rejected(change):
    catalog = legacy_catalog()
    before = original_resource(
        catalog, resource_type="knowledge_space" if change == "reverse" else "knowledge_file", model_key="owner"
    )
    before = replace(before, mode=target(before, parent_type="knowledge_library", parent_id="40"))
    mode = target(
        before,
        **(
            {"resource_type": "knowledge_library"}
            if change == "reverse"
            else {"parent_type": None, "parent_id": None}
            if change == "clear_parent"
            else {"parent_id": "41"}
        ),
    )
    with pytest.raises(PermissionMigrationBlockedError):
        compile_resource(mapped(catalog), before, mode)


@pytest.mark.parametrize("bad", ["tuple", "contribution", "missing-backing", "locator", "subject", "owner-key"])
async def test_active_and_retired_sources_require_exact_original_canonical_backing(original, bad):
    _, catalog, before = original
    retired = before.visible_sources[-1]
    changes = {
        "tuple": {"tuple_fingerprint": "f" * 64},
        "contribution": {"contribution_fingerprint": "f" * 64},
        "locator": {"source_locator": "caller"},
        "subject": {"projected_subject": "user:99"},
        "owner-key": {"source_owner_key": "grant_assignee:999"},
    }
    if bad == "missing-backing":
        before = replace(before, assignees=tuple(row for row in before.assignees if row.state != "INACTIVE"))
    else:
        before = replace(
            before,
            visible_sources=(
                *before.visible_sources[:-1],
                replace(retired, source=retired.source.model_copy(update=changes[bad])),
            ),
        )
    with pytest.raises(PermissionMigrationBlockedError):
        compile_resource(mapped(catalog), before, target(before, resource_type="knowledge_space"))


async def test_original_compiler_collision_checks_stay_active_and_new_tuple_fingerprint_is_its_output(
    original, monkeypatch
):
    _, catalog, before = original
    compiler = VisibilityProjectionCompiler
    original_compile, hits = compiler._compile_source, []

    def observed(tenant, grant, source):
        value = original_compile(tenant, grant, source)
        hits.append((grant.resource_type, source.source_id, value.tuple_fingerprint))
        return value

    monkeypatch.setattr(compiler, "_compile_source", staticmethod(observed))
    result = compile_resource(mapped(catalog), before, target(before, resource_type="knowledge_space"))
    for row in result.after.visible_sources:
        assert ("knowledge_space", int(row.source.source_owner_key.split(":")[1]), row.source.tuple_fingerprint) in hits
    with pytest.raises(ValueError, match="collision"):
        compiler._assert_same_canonical_source(before.visible_sources[0].source, result.after.visible_sources[0].source)


async def test_inactive_grant_retains_every_retired_row_and_its_original_backing_sources(original):
    _, catalog, before = original
    before = replace(
        before,
        grants=tuple(replace(row, state="INACTIVE") for row in before.grants),
        visible_sources=tuple(
            replace(row, source=row.source.model_copy(update={"state": "RETIRED"})) for row in before.visible_sources
        ),
    )
    result = compile_resource(mapped(catalog), before, target(before, resource_type="knowledge_space"))
    assert result.after.assignees == before.assignees and not result.visible_subjects and not result.visibility_deltas
    assert all(row.source.state == "RETIRED" for row in result.after.visible_sources)
    assert tuple(row.id for row in result.after.visible_sources) == tuple(row.id for row in before.visible_sources)
    assert verify.verify_resource_retirement(plan=result, actual=result.after).complete


@pytest.mark.parametrize("bad", ["parent", "operation", "source-version", "source-operation", "migration-item"])
async def test_mutable_original_mode_or_retired_metadata_is_never_signed(original, bad):
    _, catalog, before = original
    if bad in {"parent", "operation"}:
        before = replace(
            before,
            mode=replace(
                before.mode,
                **(
                    {"parent_type": "knowledge_library", "parent_id": ["40"]}
                    if bad == "parent"
                    else {"operation_id": [19]}
                ),
            ),
        )
    else:
        field = {
            "source-version": "source_version",
            "source-operation": "operation_id",
            "migration-item": "migration_item_id",
        }[bad]
        row = before.visible_sources[-1]
        before = replace(
            before,
            visible_sources=(
                *before.visible_sources[:-1],
                replace(row, source=row.source.model_copy(update={field: [19]})),
            ),
        )
    with pytest.raises(PermissionMigrationBlockedError):
        compile_resource(mapped(catalog), before, target(before, resource_type="knowledge_space"))


@pytest.mark.parametrize(
    "bad", ["target", "mode", "source", "source-version", "retired", "grant-version", "missing", "hash"]
)
async def test_verifier_rebuild_binds_complete_target_after_and_preserved_provenance(original, bad):
    _, catalog, before = original
    result = compile_resource(mapped(catalog), before, target(before, resource_type="knowledge_space"))
    if bad == "target":
        changed = replace(result, namespace_target=before.mode)
    elif bad == "missing":
        changed = replace(result, after=None)
    elif bad == "hash":
        changed = replace(result, checksum="f" * 64)
    else:
        after = result.after
        if bad == "mode":
            after = replace(after, mode=replace(after.mode, parent_type="folder", parent_id="999"))
        elif bad == "grant-version":
            after = replace(after, grants=tuple(replace(row, version=row.version + 1) for row in after.grants))
        elif bad == "source":
            after = replace(after, assignees=after.assignees[:-1])
        else:
            field, value = ("state", "ACTIVE") if bad == "retired" else ("source_version", 18)
            old = after.visible_sources[-1]
            after = replace(
                after,
                visible_sources=(
                    *after.visible_sources[:-1],
                    replace(old, source=old.source.model_copy(update={field: value})),
                ),
            )
        changed = replace(result, after=after)
    with pytest.raises(PermissionMigrationBlockedError):
        verify.verify_resource_retirement(plan=changed, actual=result.after)
    if bad not in {"target", "missing", "hash"}:
        with pytest.raises(PermissionMigrationBlockedError):
            verify.verify_resource_retirement(plan=result, actual=changed.after)


async def test_batch_requires_exact_target_pairing_and_complete_verification_without_truncation(original):
    _, baseline, before = original
    catalog, mode = mapped(baseline), target(before, resource_type="knowledge_space")
    for targets in (None, (), (mode, mode), ({},)):
        with pytest.raises(PermissionMigrationBlockedError):
            tuple(plans.build_resource_retirement_plans(catalog_plan=catalog, before=(before,), target_modes=targets))
    stream = plans.build_resource_retirement_plans(catalog_plan=catalog, before=(before, before), target_modes=(mode,))
    first = next(stream)
    with pytest.raises(PermissionMigrationBlockedError):
        next(stream)
    assert tuple(plans.build_resource_retirement_plans(catalog_plan=catalog, before=(), target_modes=())) == ()
    reports = verify.verify_resource_retirements(catalog_plan=catalog, plans=(first, first), actual=(first.after,))
    assert next(reports).complete
    with pytest.raises(PermissionMigrationBlockedError):
        next(reports)


async def test_no_mapping_uses_same_before_object_and_exact_legacy_payload_and_checksum(original):
    _, catalog, before = original
    legacy = build(catalog)
    result = plans.build_resource_retirement_plan(catalog_plan=legacy, before=before)
    assert result.after is before and result.namespace_target is None
    payload = (
        legacy.checksum,
        before,
        result.after_grants,
        result.visible_subjects,
        result.visibility_deltas,
        result.expected_use_changes,
    )
    assert plans._resource_payload(result) == payload and result.checksum == plans._checksum(payload)
    assert verify.verify_resource_retirement(plan=result, actual=before).complete
    with pytest.raises(PermissionMigrationBlockedError):
        compile_resource(legacy, before, before.mode)
    with pytest.raises(PermissionMigrationBlockedError):
        tuple(plans.build_resource_retirement_plans(catalog_plan=legacy, before=(), target_modes=()))
