"""Existing untiered empty models retain evidence-backed visibility only."""

from dataclasses import replace

import pytest

from bisheng.common.errcode.permission import PermissionMigrationBlockedError, PermissionModelStateConflictError
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.model_policy import CustomModelSelection
from bisheng.permission.domain.services.visibility_projection_service import VisibilityProjectionCompiler
from bisheng.permission.migration import f118_plan as plans
from bisheng.permission.migration import f118_verify
from test.knowledge_unification.test_perm_migration import after_catalog, source
from test.knowledge_unification.test_permission_floor_retirement_signing import legacy_catalog
from test.permission.test_f048_grant_policy import _context, _service


def catalog():
    return legacy_catalog(customs=(CustomModelSelection("legacy-empty", "Existing empty", ()),))


def original_resource():
    assignees = (source(plans, 101, 11), source(plans, 102, 11, protected=True))
    snapshot = GrantSnapshot(
        "11",
        101,
        "channel",
        "channel-1",
        GrantModelSnapshot("legacy-empty", True, ()),
        True,
        tuple(row.to_source_record() for row in assignees),
    )
    # These are pre-existing, persisted facts, not a newly authorized grant.
    visible = tuple(
        plans.PermissionVisibleSourceBaseline(i, VisibilityProjectionCompiler._compile_source(101, snapshot, row))
        for i, row in enumerate(snapshot.sources, 1)
    )
    return plans.PermissionResourceBaseline(
        101,
        "channel",
        "channel-1",
        plans.ResourceModeBaseline(7, 101, "channel", "channel-1", "CUSTOM"),
        (plans.PermissionGrantBaseline(11, 101, "channel", "channel-1", "legacy-empty", "ACTIVE"),),
        assignees,
        visible,
    ), snapshot


def test_retirement_preserves_the_exact_untiered_empty_definition_and_existing_sources():
    before = catalog()
    plan = plans.build_catalog_retirement_plan(
        run_id="legacy-empty",
        writer_contract_version="f118-v1",
        before=before,
        target_model_checksum="f" * 64,
    )
    previous = next(model for model in before.models if model.model_key == "legacy-empty")
    current = next(model for model in plan.after_models if model.model_key == "legacy-empty")
    assert current == previous
    assert current.derived_level is current.visibility_level is None
    assert not current.selected_action_codes and not current.visibility_only_resource_types
    assert f118_verify.verify_catalog_retirement(plan=plan, actual=after_catalog(plan)).complete
    original, _ = original_resource()
    converted = plans.build_resource_retirement_plan(catalog_plan=plan, before=original)
    assert converted.before == original
    assert converted.visibility_deltas == ()
    assert converted.visible_subjects == ("user:7",)
    assert converted.after_grants[0].model.derived_level is None
    assert converted.after_grants[0].sources == tuple(row.to_source_record() for row in original.assignees)
    assert f118_verify.verify_resource_retirement(plan=converted, actual=original).complete


def test_projection_preserves_only_preexisting_canonical_contributions():
    original, grant = original_resource()
    existing = tuple(row.source for row in original.visible_sources)
    result = VisibilityProjectionCompiler().compile(tenant_id=101, grants=(grant,), existing_sources=existing)
    assert result.active_sources == existing
    assert result.deltas == result.retired_sources == ()


@pytest.mark.parametrize(
    "change", ["absent", "retired", "subject", "owner", "fingerprint", "tuple", "version", "duplicate"]
)
def test_missing_or_changed_visibility_evidence_cannot_enable_an_untiered_source(change):
    original, grant = original_resource()
    existing = [row.source for row in original.visible_sources]
    updates = {
        "retired": {"state": "RETIRED"},
        "subject": {"projected_subject": "user:other"},
        "owner": {"source_owner_key": "grant_assignee:999"},
        "fingerprint": {"source_fingerprint": "0" * 64},
        "tuple": {"tuple_fingerprint": "0" * 64},
        "version": {"source_version": 2},
    }
    if change == "absent":
        existing = existing[1:]
    elif change == "duplicate":
        existing.append(existing[0])
    else:
        existing[0] = existing[0].model_copy(update=updates[change])
    with pytest.raises(ValueError):
        VisibilityProjectionCompiler().compile(tenant_id=101, grants=(grant,), existing_sources=tuple(existing))


def test_new_subject_or_scope_cannot_borrow_existing_visibility_evidence():
    original, grant = original_resource()
    existing = tuple(row.source for row in original.visible_sources)
    new = GrantSourceService().canonicalize_source(
        source_id=103, subject_type="user", subject_id="99", source_type="DIRECT"
    )
    for changed in (replace(grant, sources=(*grant.sources, new)), replace(grant, resource_id="other")):
        with pytest.raises(ValueError):
            VisibilityProjectionCompiler().compile(tenant_id=101, grants=(changed,), existing_sources=existing)


def test_removing_one_contribution_preserves_the_union_and_last_removal_retires_visibility():
    original, grant = original_resource()
    existing = tuple(row.source for row in original.visible_sources)
    partial = replace(grant, sources=grant.sources[1:])
    result = VisibilityProjectionCompiler().compile(tenant_id=101, grants=(partial,), existing_sources=existing)
    assert not result.deltas and len(result.active_sources) == len(result.retired_sources) == 1
    final = VisibilityProjectionCompiler().compile(tenant_id=101, grants=(), existing_sources=result.active_sources)
    assert [(delta.action, delta.relation) for delta in final.deltas] == [("DELETE", "visible")]


@pytest.mark.parametrize("system_authorized", [False, True])
def test_compatibility_does_not_grant_new_assignment_or_management_rights(system_authorized):
    service, _, _, _, _ = _service()
    model = GrantModelSnapshot("legacy-empty", True, ())
    context = replace(_context(capabilities=(), system_authorized=system_authorized), models=(model,))
    assert service.grantable_models(context) == ()
    assert (
        service.manageable_models_for_capabilities(
            models=(model,), capabilities=(), system_authorized=system_authorized
        )
        == ()
    )
    with pytest.raises(PermissionModelStateConflictError):
        service.require_grantable_model(context, model.model_key)
    with pytest.raises(PermissionModelStateConflictError):
        service.require_manageable_existing_model(context, model.model_key)


@pytest.mark.parametrize(
    "change", [{"derived_level": 1}, {"allow_same_level": True}, {"selected_action_codes": ("edit",)}]
)
def test_inconsistent_empty_definitions_still_block_migration(change):
    before = catalog()
    broken = replace(
        before, models=tuple(replace(m, **change) if m.model_key == "legacy-empty" else m for m in before.models)
    )
    with pytest.raises(PermissionMigrationBlockedError):
        plans.build_catalog_retirement_plan(
            run_id="legacy-empty", writer_contract_version="f118-v1", before=broken, target_model_checksum="f" * 64
        )


def f048_resource():
    from bisheng.permission.migration.f048_tuple_mapper import _checksum

    original, grant = original_resource()
    assignees = []
    for row in original.assignees:
        ref = f"channel:channel-1:user:{row.subject_id}:viewer:-"
        payload = {
            name: getattr(row, name)
            for name in (
                "include_children",
                "protected",
                "source_type",
                "subject_id",
                "subject_type",
                "userset_relation",
            )
        }
        payload["source_ref"] = ref
        assignees.append(
            replace(
                row,
                source_ref=ref,
                source_locator=f"migration:{row.source_type}:{ref}",
                source_fingerprint=_checksum(payload),
            )
        )
    grant = replace(grant, sources=tuple(row.to_source_record() for row in assignees))
    visible = tuple(
        plans.PermissionVisibleSourceBaseline(i, VisibilityProjectionCompiler._compile_source(101, grant, row))
        for i, row in enumerate(grant.sources, 1)
    )
    return replace(original, assignees=tuple(assignees), visible_sources=visible), grant


def test_actual_f048_writer_identity_is_preserved_without_recanonicalizing_sources():
    original, grant = f048_resource()
    converted = plans.build_resource_retirement_plan(
        catalog_plan=plans.build_catalog_retirement_plan(
            run_id="legacy-empty", writer_contract_version="f118-v1", before=catalog(), target_model_checksum="f" * 64
        ),
        before=original,
    )
    assert not converted.visibility_deltas
    assert converted.after_grants[0].sources == grant.sources
    assert f118_verify.verify_resource_retirement(plan=converted, actual=original).complete


@pytest.mark.parametrize(
    "change",
    ["locator", "fingerprint", "projected_subject", "subject_id", "include_children", "source_type", "source_ref"],
)
def test_f048_source_protocol_still_rejects_tampered_identity(change):
    original, _ = f048_resource()
    updates = {
        "locator": {"source_locator": "migration:DIRECT:other"},
        "fingerprint": {"source_fingerprint": "0" * 64},
        "projected_subject": {"projected_subject": "user:99"},
        "subject_id": {"subject_id": "99"},
        "include_children": {"include_children": True},
        "source_type": {"source_type": "OTHER"},
        "source_ref": {"source_ref": "other"},
    }
    changed = replace(original, assignees=(replace(original.assignees[0], **updates[change]), *original.assignees[1:]))
    with pytest.raises(PermissionMigrationBlockedError):
        plans.build_resource_retirement_plan(
            catalog_plan=plans.build_catalog_retirement_plan(
                run_id="legacy-empty",
                writer_contract_version="f118-v1",
                before=catalog(),
                target_model_checksum="f" * 64,
            ),
            before=changed,
        )


@pytest.mark.parametrize("tier", [1, 2, 3, 4])
def test_scoped_empty_tiered_model_also_preserves_only_its_existing_contribution(tier):
    original, grant = original_resource()
    scoped = replace(grant, model=replace(grant.model, derived_level=tier))
    existing = tuple(row.source for row in original.visible_sources)
    assert not VisibilityProjectionCompiler().compile(tenant_id=101, grants=(scoped,), existing_sources=existing).deltas
    with pytest.raises(ValueError):
        VisibilityProjectionCompiler().compile(tenant_id=101, grants=(scoped,), existing_sources=())
