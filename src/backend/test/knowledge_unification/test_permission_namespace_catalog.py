"""T989: explicit Catalog namespace intent, without resource write authority."""

from dataclasses import FrozenInstanceError, replace

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.domain.services.model_policy import CustomModelSelection
from bisheng.permission.migration import f118_plan as plans
from bisheng.permission.migration import f118_verify as verify
from test.knowledge_unification import test_perm_migration_snapshot as native
from test.knowledge_unification.test_perm_migration import after_catalog, resource
from test.knowledge_unification.test_perm_migration_snapshot import storage as storage
from test.knowledge_unification.test_permission_floor_retirement_signing import legacy_catalog, model

MAPPING = (("knowledge_library", "knowledge_space"),)
REASON = "document_library_to_knowledge_space_existing_capabilities"


def build(before, **kwargs):
    return plans.build_catalog_retirement_plan(
        run_id="namespace-native",
        writer_contract_version="f118-c4",
        before=before,
        target_model_checksum="f" * 64,
        **kwargs,
    )


def applicable(actions, current, kind):
    return tuple(
        action.code
        for action in actions
        if action.code in current.effective_action_codes and kind in action.resource_types
    )


def test_unmapped_legacy_control_retains_fixed_prechange_checksum():
    result = build(legacy_catalog())
    assert result.checksum == "24a64a6bb820237ccb1fad43b1e72e981e032a139b0ccbbbce42493762647731"
    assert verify.verify_catalog_retirement(plan=result, actual=after_catalog(result)).complete


def test_empty_mapping_preserves_original_payload_models_hash_and_resource_control():
    before = legacy_catalog()
    default = build(before)
    explicit = build(before, namespace_type_mappings=())
    assert explicit == default
    assert default.namespace_type_mappings == default.namespace_applicability_changes == ()
    original_payload = (
        default.run_id,
        default.writer_contract_version,
        before,
        default.target_model_checksum,
        default.after_actions,
        default.after_models,
        default.action_checksum,
        default.model_checksum,
    )
    assert plans._catalog_payload(default) == original_payload
    assert default.checksum == plans._checksum(original_payload)
    assert "knowledge_space" not in model(default, "pure-use", after=True).visibility_only_resource_types
    original = resource(plans, before, resource_type="knowledge_library", model_key="mixed-use")
    result = plans.build_resource_retirement_plan(catalog_plan=default, before=original)
    assert verify.verify_resource_retirement(plan=result, actual=original).complete


def test_mapping_records_all_models_in_canonical_order_without_changing_scopes_or_selection():
    before = legacy_catalog(
        customs=(
            CustomModelSelection("mixed", "Mixed", ("download", "use")),
            CustomModelSelection("pure", "Pure", ("use",)),
            CustomModelSelection("chosen-rename", "Chosen rename", ("rename",)),
            CustomModelSelection(
                "tool-visible", "Tool visible", (), visibility_only_resource_types=("tool",), visibility_level=1
            ),
            CustomModelSelection(
                "library-visible",
                "Library visible",
                (),
                visibility_only_resource_types=("knowledge_library",),
                visibility_level=1,
            ),
        )
    )
    result = build(before, namespace_type_mappings=MAPPING)
    default = build(before)
    assert result.namespace_type_mappings == MAPPING
    assert result.after_actions == default.after_actions == tuple(row for row in before.actions if row.code != "use")
    assert result.action_checksum == default.action_checksum and result.checksum != default.checksum
    matrix = result.namespace_applicability_changes
    assert tuple(row.model_key for row in matrix) == tuple(row.model_key for row in before.models)
    assert len(matrix) == len(before.models)
    for original, current, change in zip(before.models, result.after_models, matrix, strict=True):
        assert change.from_resource_type == "knowledge_library" and change.to_resource_type == "knowledge_space"
        assert change.before_action_codes == applicable(before.actions, original, "knowledge_library")
        assert change.after_action_codes == applicable(result.after_actions, current, "knowledge_space")
        assert change.reason == REASON
        assert current.selected_action_codes == tuple(code for code in original.selected_action_codes if code != "use")
        assert set(current.effective_action_codes) == set(original.effective_action_codes) - {"use"}
        assert (current.model_key, current.kind, current.derived_level, current.active, current.allow_same_level) == (
            original.model_key,
            original.kind,
            original.derived_level,
            original.active,
            original.allow_same_level,
        )
    by_key = {row.model_key: row for row in matrix}
    assert {"create_folder", "upload_file"} <= set(by_key["editor"].after_action_codes) - set(
        by_key["editor"].before_action_codes
    )
    assert "share" in set(by_key["manager"].after_action_codes) - set(by_key["manager"].before_action_codes)
    assert "share" in by_key["owner"].after_action_codes
    assert by_key["chosen-rename"].after_action_codes == ()  # Rename applies only to folder/file.
    assert model(result, "chosen-rename", after=True).effective_action_codes == ("rename",)
    assert "edit" not in by_key["chosen-rename"].after_action_codes
    assert by_key["pure"].before_action_codes == ("use",) and by_key["pure"].after_action_codes == ()
    for key in ("pure", "mixed", "library-visible"):
        assert {"knowledge_library", "knowledge_space"} <= set(
            model(result, key, after=True).visibility_only_resource_types
        )
    assert model(result, "mixed", after=True).retired_use_level_floor == 3
    assert model(result, "pure", after=True).retired_use_level_floor is None
    assert model(result, "tool-visible", after=True).visibility_only_resource_types == ("tool",)
    with pytest.raises(FrozenInstanceError):
        matrix[0].reason = "caller"
    assert verify.verify_catalog_retirement(plan=result, actual=after_catalog(result)).complete


def test_original_model_storage_order_never_pairs_one_models_capabilities_with_another():
    original = legacy_catalog()
    before = replace(original, models=original.models[::-1], actions=original.actions[::-1])
    result = build(before, namespace_type_mappings=MAPPING)
    assert tuple(row.model_key for row in result.namespace_applicability_changes) == tuple(
        row.model_key for row in before.models
    )
    for change in result.namespace_applicability_changes:
        previous = model(before, change.model_key)
        current = model(result, change.model_key, after=True)
        assert change.before_action_codes == applicable(original.actions, previous, "knowledge_library")
        assert change.after_action_codes == applicable(result.after_actions, current, "knowledge_space")


def test_mapping_never_invents_library_or_space_provenance_for_an_unrelated_old_use_scope():
    original = legacy_catalog()
    before = replace(
        original,
        actions=tuple(
            replace(row, resource_types=frozenset({"tool"})) if row.code == "use" else row for row in original.actions
        ),
    )
    result = build(before, namespace_type_mappings=MAPPING)
    assert model(result, "pure-use", after=True).visibility_only_resource_types == ("tool",)
    assert model(result, "mixed-use", after=True).visibility_only_resource_types == ("tool",)


def test_matrix_values_cannot_hold_mutable_action_collections_or_bypass_an_empty_plan():
    result = build(legacy_catalog(), namespace_type_mappings=MAPPING)
    entry = result.namespace_applicability_changes[0]
    with pytest.raises(TypeError):
        replace(entry, after_action_codes=["edit"])
    empty = build(result.before)
    with pytest.raises(PermissionMigrationBlockedError):
        verify.verify_catalog_retirement(
            plan=replace(empty, namespace_applicability_changes=(entry,)), actual=after_catalog(empty)
        )


def test_mapping_rejects_tuple_subclasses_instead_of_accepting_mutable_semantic_overrides():
    class TupleSubclass(tuple):
        pass

    class StringSubclass(str):
        pass

    for mapping in (
        TupleSubclass(MAPPING),
        (TupleSubclass(MAPPING[0]),),
        ((StringSubclass("knowledge_library"), "knowledge_space"),),
    ):
        with pytest.raises(PermissionMigrationBlockedError):
            build(legacy_catalog(), namespace_type_mappings=mapping)


@pytest.mark.parametrize(
    "mapping",
    [
        None,
        [],
        [list(MAPPING[0])],
        (list(MAPPING[0]),),
        (("knowledge_space", "knowledge_library"),),
        MAPPING * 2,
        (("knowledge_library", "folder"),),
        (*MAPPING, ("knowledge_space", "folder")),
        ("knowledge_library", "knowledge_space"),
        (("knowledge_library",),),
        ((True, "knowledge_space"),),
    ],
)
def test_only_native_immutable_empty_or_one_approved_mapping_is_accepted(mapping):
    with pytest.raises(PermissionMigrationBlockedError):
        build(legacy_catalog(), namespace_type_mappings=mapping)


@pytest.mark.parametrize("tamper", ["mapping", "removed", "matrix", "order", "reason", "actions", "provenance"])
def test_catalog_verifier_rebuild_binds_the_entire_mapping_matrix_and_after_metadata(tamper):
    result = build(legacy_catalog(), namespace_type_mappings=MAPPING)
    matrix = result.namespace_applicability_changes
    if tamper == "mapping":
        changed = replace(result, namespace_type_mappings=(("knowledge_space", "knowledge_library"),))
    elif tamper == "removed":
        changed = replace(result, namespace_type_mappings=())
    elif tamper == "matrix":
        changed = replace(result, namespace_applicability_changes=matrix[:-1])
    elif tamper == "order":
        changed = replace(result, namespace_applicability_changes=matrix[::-1])
    elif tamper in {"reason", "actions"}:
        row = replace(matrix[0], **({"reason": "other"} if tamper == "reason" else {"after_action_codes": ("edit",)}))
        changed = replace(result, namespace_applicability_changes=(row, *matrix[1:]))
    else:
        changed = replace(
            result,
            after_models=tuple(
                replace(
                    row,
                    visibility_only_resource_types=tuple(
                        value for value in row.visibility_only_resource_types if value != "knowledge_library"
                    ),
                )
                if row.model_key == "pure-use"
                else row
                for row in result.after_models
            ),
        )
    with pytest.raises(PermissionMigrationBlockedError):
        verify.verify_catalog_retirement(plan=changed, actual=after_catalog(result))


@pytest.mark.parametrize("kind", ["knowledge_library", "knowledge_space", "knowledge_file", "tool"])
def test_mapped_catalog_cannot_authorize_any_resource_builder_or_old_before_verifier(kind):
    before = legacy_catalog()
    original = resource(plans, before, resource_type=kind, model_key="owner")
    unchanged = plans.build_resource_retirement_plan(catalog_plan=build(before), before=original)
    mapped = build(before, namespace_type_mappings=MAPPING)
    with pytest.raises(PermissionMigrationBlockedError):
        plans.build_resource_retirement_plan(catalog_plan=mapped, before=original)
    with pytest.raises(PermissionMigrationBlockedError):
        tuple(plans.build_resource_retirement_plans(catalog_plan=mapped, before=(original,)))
    with pytest.raises(PermissionMigrationBlockedError):
        verify.verify_resource_retirement(plan=replace(unchanged, catalog_plan=mapped), actual=original)
    with pytest.raises(PermissionMigrationBlockedError):
        tuple(verify.verify_resource_retirements(catalog_plan=mapped, plans=(), actual=()))
    assert original == unchanged.before


async def test_actual_sql_catalog_snapshot_build_verify_are_read_only_and_grants_stay_original(
    storage,
    monkeypatch,
):
    original = legacy_catalog()
    monkeypatch.setattr(native, "baseline", lambda _module: original)
    async with AsyncSession(storage) as session, session.begin():
        await native.seed_catalog(session)
        monkeypatch.setattr(
            native,
            "resource",
            lambda _module: resource(plans, original, resource_type="knowledge_library", model_key="mixed-use"),
        )
        await native.seed_rows(session)
    statements = []
    async with AsyncSession(storage) as session, session.begin():
        engine = session.bind.sync_engine

        def capture(_c, _cu, sql, _p, _ctx, _many):
            statements.append(sql.lstrip().split()[0].upper())

        sa.event.listen(engine, "before_cursor_execute", capture)
        try:
            repo = PermissionMigrationSnapshotRepository()
            before = await repo.aload_catalog_baseline(session, environment="test")
            assert before == original
            original_grants = await repo.alist_grants(session)
            original_sources = await repo.alist_assignees(session)
            result = build(before, namespace_type_mappings=MAPPING)
            assert verify.verify_catalog_retirement(plan=result, actual=after_catalog(result)).complete
            assert await repo.alist_grants(session) == original_grants
            assert await repo.alist_assignees(session) == original_sources
            assert await repo.aload_catalog_baseline(session, environment="test") == original
            assert not session.new and not session.dirty and not session.deleted
        finally:
            sa.event.remove(engine, "before_cursor_execute", capture)
    assert statements and set(statements) == {"SELECT"}


@pytest.mark.parametrize("count", [401, 1001])
def test_matrix_constructs_one_candidate_per_model_and_derives_catalog_only_once(monkeypatch, count):
    before = legacy_catalog(
        customs=tuple(CustomModelSelection(f"custom-{i}", f"Custom {i}", ("download", "use")) for i in range(count - 4))
    )
    candidates, derivations = [], []
    init = plans.ModelApplicabilityChange.__init__
    derive = plans.derive_permission_models

    def construct(self, *args, **kwargs):
        candidates.append(1)
        init(self, *args, **kwargs)

    def compile_once(*args, **kwargs):
        derivations.append(1)
        return derive(*args, **kwargs)

    monkeypatch.setattr(plans.ModelApplicabilityChange, "__init__", construct)
    monkeypatch.setattr(plans, "derive_permission_models", compile_once)
    result = build(before, namespace_type_mappings=MAPPING)
    assert len(candidates) == len(result.namespace_applicability_changes) == len(before.models) == count
    assert len(derivations) == 1
    assert len({row.model_key for row in result.namespace_applicability_changes}) == len(before.models)
    print({"models": count, "matrix_candidates": len(candidates), "catalog_derivations": len(derivations)})
