"""T981: issue only the exact original tier of a supported old mixed-use model."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.common.errcode.permission import PermissionMigrationBlockedError, PermissionPublishNotReadyError
from bisheng.knowledge.application import unification_inventory_codec as codec
from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore
from bisheng.permission.application import control_state
from bisheng.permission.application.catalog_api import SqlCatalogState
from bisheng.permission.domain.models import AuthorizationModelRelease, PermissionCatalogRelease, PermissionModel
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.domain.services.catalog_policy import (
    ACTION_RESOURCE_SCOPES,
    REGISTERED_ACTION_CODES,
    CatalogAction,
    derive_action_release,
)
from bisheng.permission.domain.services.model_policy import CustomModelSelection, derive_permission_models
from bisheng.permission.migration import f118_plan as plans
from bisheng.permission.migration import f118_verify as verify
from bisheng.permission.migration.f048_model_mapper import INITIAL_ACTION_LEVELS
from test.knowledge_unification import test_perm_migration_snapshot as native
from test.knowledge_unification.test_perm_control_snapshot import session_factory as session_factory
from test.knowledge_unification.test_perm_migration import after_catalog, baseline, resource

OLD_USE_SCOPES = frozenset({"app", "assistant", "knowledge_library", "linsight_skill", "tool", "workflow"})


def legacy_catalog(*, use_level=3, use_active=True, customs=None):
    # Actual old F048 SSOT order/scopes; official ASSIGN_ACTION_LEVEL can move
    # use to 3. Re-derive ALL before models, including pure-use and standards.
    codes = (*REGISTERED_ACTION_CODES[:9], "use", *REGISTERED_ACTION_CODES[9:])
    actions = derive_action_release(
        (
            CatalogAction(
                code,
                code,
                use_level if code == "use" else INITIAL_ACTION_LEVELS[code],
                use_active if code == "use" else True,
                OLD_USE_SCOPES if code == "use" else ACTION_RESOURCE_SCOPES[code],
                index,
            )
            for index, code in enumerate(codes)
        ),
        registered_action_codes=codes,
    )
    if customs is None:
        customs = (
            CustomModelSelection("mixed-use", "Mixed use", ("download", "use")),
            CustomModelSelection("pure-use", "Pure use", ("use",)),
            CustomModelSelection("same-tier", "Same tier", ("share", "use")),
            CustomModelSelection("inactive-model", "Inactive model", ("download", "use"), active=False),
            CustomModelSelection(
                "ordinary", "Ordinary", ("download",), visibility_only_resource_types=("tool",), visibility_level=3
            ),
        )
    models = derive_permission_models(actions, custom_models=customs)
    assert not models.blockers
    records = tuple(
        plans.PermissionModelBaseline(
            ident,
            model.model_key,
            model.name,
            model.name.casefold(),
            model.kind,
            model.config_scope,
            model.derived_level,
            model.active,
            model.allow_same_level,
            model.selected_action_codes,
            model.action_codes,
            model.visibility_only_resource_types if model.kind == "CUSTOM" else (),
            model.visibility_level if model.kind == "CUSTOM" else None,
            None,
            model.retired_use_level_floor,
        )
        for ident, model in enumerate(models.models, 1)
    )
    original = baseline(plans)
    return replace(
        original,
        actions=actions.actions,
        models=records,
        release=replace(
            original.release, checksum=plans._checksum({"actions": actions.checksum, "models": models.checksum})
        ),
    )


def build(before):
    return plans.build_catalog_retirement_plan(
        run_id="mixed-native", writer_contract_version="f118-p3", before=before, target_model_checksum="f" * 64
    )


def model(catalog, key, *, after=False):
    return next(row for row in (catalog.after_models if after else catalog.models) if row.model_key == key)


def test_only_exact_mixed_models_receive_the_original_tier_and_scopes_never_expand():
    before = legacy_catalog()
    result = build(before)
    assert {row.model_key for row in result.after_models if row.retired_use_level_floor is not None} == {
        "mixed-use",
        "inactive-model",
    }
    assert result.after_actions == tuple(action for action in before.actions if action.code != "use")
    for previous, current in zip(before.models, result.after_models, strict=True):
        assert (
            current.model_key,
            current.name,
            current.kind,
            current.active,
            current.allow_same_level,
            current.config_scope,
            current.derived_level,
            current.legacy_source_key,
        ) == (
            previous.model_key,
            previous.name,
            previous.kind,
            previous.active,
            previous.allow_same_level,
            previous.config_scope,
            previous.derived_level,
            previous.legacy_source_key,
        )
        assert set(current.effective_action_codes) == set(previous.effective_action_codes) - {"use"}
        assert set(current.selected_action_codes) == set(previous.selected_action_codes) - {"use"}
    for key in ("mixed-use", "inactive-model"):
        assert model(before, key).retired_use_level_floor is None
        current = model(result, key, after=True)
        assert current.retired_use_level_floor == current.derived_level == current.visibility_level == 3
        assert set(current.visibility_only_resource_types) == OLD_USE_SCOPES
        assert "knowledge_space" not in current.visibility_only_resource_types
    assert model(result, "pure-use", after=True).derived_level == 3
    assert model(result, "pure-use", after=True).retired_use_level_floor is None
    assert model(result, "same-tier", after=True).retired_use_level_floor is None
    assert model(result, "ordinary", after=True).derived_level == 1
    original_resource = resource(plans, before, resource_type="knowledge_library", model_key="mixed-use")
    removal = plans.build_resource_retirement_plan(catalog_plan=result, before=original_resource)
    assert not removal.visibility_deltas and removal.visible_subjects == ("user:7",)
    assert removal.after_grants[0].sources == tuple(row.to_source_record() for row in original_resource.assignees)


@pytest.mark.parametrize("use_level", [1, 2])
def test_mixed_floor_is_not_issued_when_remaining_tier_already_covers_original(use_level):
    before = legacy_catalog(use_level=use_level, customs=(CustomModelSelection("mixed", "Mixed", ("edit", "use")),))
    assert model(build(before), "mixed", after=True).retired_use_level_floor is None


def test_inactive_or_unselected_use_does_not_issue_floor():
    before = legacy_catalog(
        use_active=False,
        customs=(CustomModelSelection("inactive-use", "Inactive use", ("download", "use"), active=False),),
    )
    current = model(build(before), "inactive-use", after=True)
    assert current.retired_use_level_floor is None and current.derived_level == 1
    before = legacy_catalog(customs=(CustomModelSelection("unselected", "Unselected", ("download",)),))
    assert model(build(before), "unselected", after=True).retired_use_level_floor is None


@pytest.mark.parametrize("bad", [None, True, 0, 1, 2, 4, 3.0])
def test_original_derived_must_be_the_actual_canonical_effective_maximum(bad):
    before = legacy_catalog(customs=(CustomModelSelection("mixed-use", "Mixed use", ("download", "use")),))
    before = replace(
        before,
        models=tuple(replace(row, derived_level=bad) if row.model_key == "mixed-use" else row for row in before.models),
    )
    with pytest.raises(PermissionMigrationBlockedError):
        build(before)


def test_existing_visibility_tier_conflict_is_not_overwritten_and_legacy_source_key_is_preserved():
    before = legacy_catalog()
    conflict = replace(model(before, "mixed-use"), visibility_only_resource_types=("tool",), visibility_level=2)
    with pytest.raises(PermissionMigrationBlockedError):
        build(
            replace(
                before, models=tuple(conflict if row.model_key == conflict.model_key else row for row in before.models)
            )
        )
    original = replace(model(before, "mixed-use"), legacy_source_key="actual-legacy-original")
    result = build(
        replace(before, models=tuple(original if row.model_key == original.model_key else row for row in before.models))
    )
    assert model(result, "mixed-use", after=True).legacy_source_key == "actual-legacy-original"


def test_already_issued_floor_is_carried_without_new_authority():
    before = legacy_catalog(
        customs=(
            CustomModelSelection(
                "existing",
                "Existing",
                ("download",),
                visibility_only_resource_types=("tool",),
                visibility_level=3,
                retired_use_level_floor=3,
            ),
        )
    )
    assert model(build(before), "existing", after=True) == model(before, "existing")


@pytest.mark.parametrize("tamper", ["remove", "lower"])
def test_verifier_rebuild_rejects_any_modified_floor(tamper):
    result = build(legacy_catalog())
    assert verify.verify_catalog_retirement(plan=result, actual=after_catalog(result)).complete
    changed = (
        replace(model(result, "mixed-use", after=True), retired_use_level_floor=None)
        if tamper == "remove"
        else replace(model(result, "mixed-use", after=True), retired_use_level_floor=2, visibility_level=2)
    )
    result = replace(
        result,
        after_models=tuple(changed if row.model_key == changed.model_key else row for row in result.after_models),
    )
    with pytest.raises(PermissionMigrationBlockedError):
        verify.verify_catalog_retirement(plan=result, actual=after_catalog(result))


async def test_real_snapshot_plan_artifact_catalog_reload_and_current_are_one_native_component(
    session_factory, tenant_context, monkeypatch
):
    tenant_context(101)
    original = legacy_catalog()
    monkeypatch.setattr(native, "baseline", lambda _module: original)
    async with session_factory() as session, session.begin():
        await native.seed_catalog(session)
        observed = await PermissionMigrationSnapshotRepository().aload_catalog_baseline(session, environment="test")
        assert observed == original
        result = build(observed)
    objects = {}

    async def exists(**kw):
        return kw["object_name"] in objects

    async def put(**kw):
        objects[kw["object_name"]] = kw["file"]

    async def get(**kw):
        return objects[kw["object_name"]]

    store = UnificationArtifactStore(
        SimpleNamespace(bucket="durable", tmp_bucket="temporary", object_exists=exists, put_object=put, get_object=get)
    )
    records = tuple(codec.record_from_row(row) for row in result.after_models)
    arguments = {
        "run_id": result.run_id,
        "section": "catalog",
        "scope": "global",
        "tenant_id": None,
        "page_index": 0,
        "kind": "plan",
    }
    content = codec.encode_inventory_page(**arguments, records=records)
    descriptor = await store.aput_canonical(run_id=result.run_id, kind="plan", content=content)
    decoded = codec.decode_inventory_page(
        await store.aload_canonical(descriptor, run_id=result.run_id, kind="plan"), **arguments
    )
    assert decoded.records == records
    actions, models, _ = plans._compile_catalog(observed)
    after = after_catalog(result)
    async with session_factory() as session, session.begin():
        old = await session.get(PermissionCatalogRelease, observed.release.id)
        old.status = "RETIRED"
        session.add(AuthorizationModelRelease(**plans._json(after.authorization)))
        session.add(PermissionCatalogRelease(**plans._json(after.release)))
        await session.flush()
        await SqlCatalogState._replace_children(
            session, release_id=after.release.id, action_release=actions, model_release=models
        )
    sessions = session_factory

    monkeypatch.setattr(control_state, "get_async_db_session", sessions)
    state = SqlCatalogState(session_factory=sessions)
    loaded = await state.load_snapshot(after.release.id)
    assert next(row for row in loaded.model_release.models if row.model_key == "mixed-use").retired_use_level_floor == 3
    current = await control_state.SqlPermissionControlState().current_catalog()
    assert next(row.snapshot.derived_level for row in current.models if row.snapshot.model_key == "mixed-use") == 3
    async with sessions() as session, session.begin():
        actual = await PermissionMigrationSnapshotRepository().aload_catalog_baseline(session, environment="test")
    assert verify.verify_catalog_retirement(plan=result, actual=actual).complete
    objects[descriptor["object_key"]] = content.replace(b'"retired_use_level_floor":3', b'"retired_use_level_floor":2')
    with pytest.raises(ReferenceCoverageNotReadyError):
        await store.aload_canonical(descriptor, run_id=result.run_id, kind="plan")
    async with sessions() as session, session.begin():
        await session.execute(
            sa.update(PermissionModel.__table__)
            .where(PermissionModel.model_key == "mixed-use", PermissionModel.catalog_release_id == after.release.id)
            .values(retired_use_level_floor=None)
        )
    with pytest.raises(PermissionPublishNotReadyError):
        await control_state.SqlPermissionControlState().current_catalog()
