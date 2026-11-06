"""T157: pure retirement plans preserve original authorization provenance.

No SQL/FGA acquisition, publication, migration or Coverage readiness is claimed.
"""

import importlib
from dataclasses import asdict, replace

import pytest

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.permission.domain.services.catalog_policy import (
    ACTION_RESOURCE_SCOPES,
    MIGRATED_RESOURCE_TYPES,
    REGISTERED_ACTION_CODES,
    CatalogAction,
    derive_action_release,
)
from bisheng.permission.domain.services.catalog_service import _checksum
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.model_policy import CustomModelSelection, derive_permission_models
from bisheng.permission.domain.services.visibility_projection_service import VisibilityProjectionCompiler


@pytest.fixture
def migration():
    return importlib.import_module("bisheng.permission.migration.f118_plan")


@pytest.fixture
def verifier():
    return importlib.import_module("bisheng.permission.migration.f118_verify")


def baseline(module):
    levels = {
        "manage_permission": 3,
        "rename": 2,
        "edit": 2,
        "create_folder": 2,
        "upload_file": 2,
        "move": 2,
        "download": 1,
        "delete": 4,
        "share": 3,
        "publish": 3,
        "unpublish": 3,
        "use": 1,
    }
    actions = tuple(
        CatalogAction(code, code, levels[code], True, ACTION_RESOURCE_SCOPES.get(code, MIGRATED_RESOURCE_TYPES), index)
        for index, code in enumerate((*REGISTERED_ACTION_CODES, "use"))
    )
    release = derive_action_release(actions, registered_action_codes=(*REGISTERED_ACTION_CODES, "use"))
    models = derive_permission_models(
        release,
        custom_models=(
            CustomModelSelection("only-use", "Only use", ("use",)),
            CustomModelSelection("file-use", "File selection", ("rename", "use", "download")),
            CustomModelSelection("inactive-use", "Inactive", ("use",), active=False),
        ),
    )
    records = tuple(
        module.PermissionModelBaseline(
            id=index,
            model_key=model.model_key,
            name=model.name,
            normalized_name=model.name.casefold(),
            kind=model.kind,
            config_scope=model.config_scope,
            derived_level=model.derived_level,
            active=model.active,
            allow_same_level=model.allow_same_level,
            selected_action_codes=model.selected_action_codes,
            effective_action_codes=model.action_codes,
            visibility_only_resource_types=model.visibility_only_resource_types,
            visibility_level=model.visibility_level,
            legacy_source_key=f"original:{model.model_key}",
        )
        for index, model in enumerate(models.models, 1)
    )
    return module.PermissionCatalogBaseline(
        release=module.CatalogReleaseBaseline(
            id=1,
            release_key="before",
            version=1,
            checksum=_checksum({"actions": release.checksum, "models": models.checksum}),
            required_authorization_model_release_id=10,
            draft_owner_id=7,
            idempotency_key="before",
        ),
        authorization=module.AuthorizationPinBaseline(
            id=10,
            environment="test",
            store_id="original-store",
            model_id="original-model",
            model_checksum="a" * 64,
            required_relations_checksum="b" * 64,
        ),
        actions=actions,
        models=records,
    )


def catalog_plan(module, before=None):
    return module.build_catalog_retirement_plan(
        run_id="formal-run",
        writer_contract_version="f118-v1",
        before=before or baseline(module),
        target_model_checksum="f" * 64,
    )


def source(module, ident, grant_id, *, state="ACTIVE", protected=False):
    original = GrantSourceService().canonicalize_source(
        source_id=ident,
        subject_type="user",
        subject_id="7",
        source_type="CREATOR" if protected else "DIRECT",
        source_ref="original",
        protected=protected,
    )
    values = asdict(original)
    del values["active"]
    values["id"] = values.pop("source_id")
    return module.PermissionAssigneeBaseline(tenant_id=101, grant_id=grant_id, state=state, **values)


def resource(module, before_catalog=None, *, resource_type="knowledge_space", model_key="only-use"):
    before_catalog = before_catalog or baseline(module)
    model = next(item for item in before_catalog.models if item.model_key == model_key)
    sources = (source(module, 1, 11), source(module, 2, 11, protected=True), source(module, 3, 11, state="INACTIVE"))
    records = tuple(item.to_source_record() for item in sources)
    grant = GrantSnapshot(
        "11",
        101,
        resource_type,
        "40",
        GrantModelSnapshot(
            model_key,
            model.active,
            model.effective_action_codes,
            model.derived_level,
            model.allow_same_level,
            model.visibility_only_resource_types,
            model.visibility_level,
        ),
        True,
        records,
    )
    visible = VisibilityProjectionCompiler().compile(tenant_id=101, grants=(grant,), existing_sources=()).active_sources
    return module.PermissionResourceBaseline(
        tenant_id=101,
        resource_type=resource_type,
        resource_id="40",
        mode=module.ResourceModeBaseline(
            id=4, tenant_id=101, resource_type=resource_type, resource_id="40", mode="CUSTOM"
        ),
        grants=(
            module.PermissionGrantBaseline(
                id=11, tenant_id=101, resource_type=resource_type, resource_id="40", model_key=model_key, state="ACTIVE"
            ),
        ),
        assignees=sources,
        visible_sources=tuple(
            module.PermissionVisibleSourceBaseline(id=i, source=item) for i, item in enumerate(visible, 1)
        ),
    )


def after_catalog(plan):
    release = replace(
        plan.before.release,
        id=2,
        release_key="after",
        version=2,
        predecessor_id=1,
        required_authorization_model_release_id=20,
        idempotency_key="after",
        checksum=_checksum(
            {
                "actions": plan.action_checksum,
                "models": plan.model_checksum,
                "predecessor_release_id": 1,
                "release_key": "after",
            }
        ),
    )
    return replace(
        plan.before,
        release=release,
        authorization=replace(plan.before.authorization, id=20, model_id="new-model", model_checksum="f" * 64),
        actions=plan.after_actions,
        models=tuple(replace(model, id=model.id + 100) for model in plan.after_models),
    )


def test_catalog_retires_only_use_and_preserves_pure_visibility_original_management_tier(migration, verifier):
    plan = catalog_plan(migration)
    assert "use" not in {action.code for action in plan.after_actions}
    assert tuple(action for action in plan.before.actions if action.code != "use") == plan.after_actions
    only = next(model for model in plan.after_models if model.model_key == "only-use")
    assert only.effective_action_codes == only.selected_action_codes == ()
    assert only.derived_level == only.visibility_level == 1
    assert set(only.visibility_only_resource_types) == MIGRATED_RESOURCE_TYPES
    inactive = next(model for model in plan.after_models if model.model_key == "inactive-use")
    assert not inactive.active
    assert verifier.verify_catalog_retirement(plan=plan, actual=after_catalog(plan)).complete


def test_resource_plan_keeps_every_original_source_protected_subject_and_union(migration, verifier):
    plan = catalog_plan(migration)
    original = resource(migration, plan.before)
    result = migration.build_resource_retirement_plan(catalog_plan=plan, before=original)
    assert result.before == original and result.visible_subjects == ("user:7",)
    assert result.visibility_deltas == ()
    assert verifier.verify_resource_retirement(plan=result, actual=original).complete
    # Retiring one contribution still leaves the independently authorized Source.
    grants = result.after_grants
    remaining = replace(grants[0], sources=tuple(item for item in grants[0].sources if item.source_id != 1))
    compiled = VisibilityProjectionCompiler().compile(
        tenant_id=101, grants=(remaining,), existing_sources=tuple(row.source for row in original.visible_sources)
    )
    assert not compiled.deltas and len(compiled.active_sources) == 1


def test_download_and_independent_rename_are_unchanged_on_the_actual_file_target(migration, verifier):
    plan = catalog_plan(migration)
    original = resource(migration, plan.before, resource_type="knowledge_file", model_key="file-use")
    result = migration.build_resource_retirement_plan(catalog_plan=plan, before=original)
    assert result.after_grants[0].model.action_codes == ("rename", "download")
    assert result.after_grants[0].model.derived_level == 2
    assert verifier.verify_resource_retirement(plan=result, actual=original).complete


@pytest.mark.parametrize("change", ["empty", "level", "scope", "unknown", "projection", "pin"])
def test_unexplained_or_unsafe_before_state_is_blocked(migration, change):
    before = baseline(migration)
    target = next(item for item in before.models if item.model_key == "only-use")
    if change == "empty":
        before = replace(
            before,
            models=tuple(
                replace(item, selected_action_codes=(), effective_action_codes=()) if item is target else item
                for item in before.models
            ),
        )
    elif change == "level":
        before = replace(
            before,
            models=tuple(replace(item, derived_level=None) if item is target else item for item in before.models),
        )
    elif change == "scope":
        before = replace(
            before,
            actions=tuple(
                replace(item, resource_types=frozenset({"knowledge_space"})) if item.code == "download" else item
                for item in before.actions
            ),
        )
    elif change == "unknown":
        before = replace(
            before, actions=(*before.actions, CatalogAction("unknown", "Unknown", 1, True, frozenset({"tool"})))
        )
    elif change == "projection":
        before = replace(before, release=replace(before.release, write_fenced=True))
    else:
        before = replace(before, release=replace(before.release, required_authorization_model_release_id=99))
    with pytest.raises(PermissionMigrationBlockedError):
        catalog_plan(migration, before)


@pytest.mark.parametrize("change", ["run", "checksum", "writer", "target"])
def test_tampered_plan_binding_cannot_be_verified(migration, verifier, change):
    plan = catalog_plan(migration)
    fields = {
        "run": {"run_id": "other"},
        "checksum": {"checksum": "0" * 64},
        "writer": {"writer_contract_version": "other"},
        "target": {"target_model_checksum": "e" * 64},
    }[change]
    with pytest.raises(PermissionMigrationBlockedError):
        verifier.verify_catalog_retirement(plan=replace(plan, **fields), actual=after_catalog(plan))


@pytest.mark.parametrize("change", ["rename", "download", "active", "level", "model", "checksum", "store"])
def test_actual_non_use_or_catalog_pin_changes_are_not_reported_as_zero_difference(migration, verifier, change):
    plan = catalog_plan(migration)
    actual = after_catalog(plan)
    if change in {"rename", "download"}:
        actual = replace(
            actual,
            actions=tuple(replace(item, active=False) if item.code == change else item for item in actual.actions),
        )
    elif change in {"active", "level"}:
        actual = replace(
            actual,
            models=tuple(
                replace(item, **({"active": False} if change == "active" else {"derived_level": 4}))
                if item.model_key == "only-use"
                else item
                for item in actual.models
            ),
        )
    elif change == "checksum":
        actual = replace(actual, release=replace(actual.release, checksum="0" * 64))
    else:
        actual = replace(
            actual,
            authorization=replace(
                actual.authorization,
                **({"model_checksum": "0" * 64} if change == "model" else {"store_id": "other-store"}),
            ),
        )
    with pytest.raises(PermissionMigrationBlockedError):
        verifier.verify_catalog_retirement(plan=plan, actual=actual)


@pytest.mark.parametrize("change", ["source", "protected", "parent", "inactive", "visible", "pending"])
def test_actual_source_and_visibility_drift_or_incomplete_projection_blocks(migration, verifier, change):
    original = resource(migration)
    plan = migration.build_resource_retirement_plan(catalog_plan=catalog_plan(migration), before=original)
    if change == "source":
        actual = replace(original, assignees=original.assignees[1:])
    elif change == "protected":
        actual = replace(original, assignees=tuple(replace(item, protected=False) for item in original.assignees))
    elif change == "inactive":
        actual = replace(original, assignees=tuple(replace(item, state="ACTIVE") for item in original.assignees))
    elif change == "visible":
        actual = replace(original, visible_sources=())
    else:
        actual = replace(
            original,
            mode=replace(
                original.mode,
                **(
                    {"parent_id": "other", "parent_type": "folder"}
                    if change == "parent"
                    else {"projection_state": "PENDING"}
                ),
            ),
        )
    with pytest.raises(PermissionMigrationBlockedError):
        verifier.verify_resource_retirement(plan=plan, actual=actual)


@pytest.mark.parametrize("field,value", [("tenant_id", 202), ("subject_id", "8"), ("projected_subject", "user:8")])
def test_original_assignee_tenant_and_canonical_subject_must_be_consistent(migration, field, value):
    original = resource(migration)
    broken = replace(original, assignees=(replace(original.assignees[0], **{field: value}), *original.assignees[1:]))
    with pytest.raises(PermissionMigrationBlockedError):
        migration.build_resource_retirement_plan(catalog_plan=catalog_plan(migration), before=broken)
