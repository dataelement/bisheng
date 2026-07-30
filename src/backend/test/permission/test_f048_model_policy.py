"""Pure standard/custom permission-model contracts.

覆盖 AC: AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14,
AC-15, AC-16, AC-17, AC-18, AC-39, AC-156
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from bisheng.permission.domain.services.catalog_policy import (
    ACTION_RESOURCE_SCOPES,
    REGISTERED_ACTION_CODES,
    CatalogAction,
    derive_action_release,
)
from bisheng.permission.domain.services.model_policy import (
    CustomModelSelection,
    ModelPreset,
    calculate_model_impact,
    derive_permission_models,
    effective_model_action_codes,
    ensure_model_deletable,
    initialize_from_preset,
    validate_standard_model_update,
    with_allow_same_level,
)

INITIAL_LEVELS = {
    "download": 1,
    "use": 1,
    "rename": 2,
    "edit": 2,
    "create_folder": 2,
    "upload_file": 2,
    "move": 2,
    "manage_permission": 3,
    "share": 3,
    "publish": 3,
    "unpublish": 3,
    "delete": 4,
}


def _action_release(
    *,
    level_overrides: dict[str, int | None] | None = None,
    inactive: frozenset[str] = frozenset(),
):
    levels = INITIAL_LEVELS | (level_overrides or {})
    return derive_action_release(
        CatalogAction(
            code=code,
            name=code,
            level=levels[code],
            active=code not in inactive,
            resource_types=ACTION_RESOURCE_SCOPES[code],
        )
        for code in REGISTERED_ACTION_CODES
    )


def _by_key(release):
    return {model.model_key: model for model in release.models}


def test_four_standard_models_are_rebuilt_cumulatively() -> None:
    models = _by_key(derive_permission_models(_action_release()))
    assert {key: model.derived_level for key, model in models.items()} == {
        "viewer": 1,
        "editor": 2,
        "manager": 3,
        "owner": 4,
    }
    assert set(models["viewer"].action_codes) == {"download", "use"}
    assert set(models["editor"].action_codes) == {
        "download",
        "use",
        "rename",
        "edit",
        "create_folder",
        "upload_file",
        "move",
    }
    assert set(models["manager"].action_codes) == set(REGISTERED_ACTION_CODES) - {"delete"}
    assert set(models["owner"].action_codes) == set(REGISTERED_ACTION_CODES)
    assert models["owner"].allow_same_level is True


def test_action_level_change_recomputes_every_standard_model() -> None:
    models = _by_key(derive_permission_models(_action_release(level_overrides={"delete": 1, "download": 4})))
    assert "delete" in models["viewer"].action_codes
    assert "download" not in models["manager"].action_codes
    assert "download" in models["owner"].action_codes


def test_standard_fields_are_immutable_but_eligible_same_level_is_mutable() -> None:
    models = _by_key(derive_permission_models(_action_release()))
    manager = models["manager"]
    validate_standard_model_update(
        manager,
        replace(manager, allow_same_level=True),
    )
    with pytest.raises(ValueError, match="immutable"):
        validate_standard_model_update(manager, replace(manager, name="renamed"))
    with pytest.raises(ValueError, match="immutable"):
        validate_standard_model_update(
            manager,
            replace(manager, action_codes=("download",)),
        )
    with pytest.raises(ValueError, match="manage_permission"):
        with_allow_same_level(models["viewer"], True)
    assert with_allow_same_level(manager, True).allow_same_level is True


def test_custom_level_uses_only_explicit_effective_actions() -> None:
    custom = CustomModelSelection(
        model_key="custom-collaborator",
        name="协作编辑",
        action_codes=("edit", "share"),
    )
    model = _by_key(derive_permission_models(_action_release(), custom_models=(custom,)))[custom.model_key]
    assert model.derived_level == 3
    assert set(model.action_codes) == {"edit", "share"}
    assert "download" not in model.action_codes


def test_empty_unknown_and_unavailable_custom_models_fail_closed() -> None:
    with pytest.raises(ValueError, match="empty"):
        derive_permission_models(
            _action_release(),
            custom_models=(
                CustomModelSelection(
                    model_key="empty",
                    name="空模型",
                    action_codes=(),
                ),
            ),
        )
    with pytest.raises(ValueError, match="unknown"):
        derive_permission_models(
            _action_release(),
            custom_models=(
                CustomModelSelection(
                    model_key="unknown",
                    name="未知动作",
                    action_codes=("not_registered",),
                ),
            ),
        )

    release = derive_permission_models(
        _action_release(level_overrides={"edit": None}),
        custom_models=(
            CustomModelSelection(
                model_key="only-edit",
                name="只编辑",
                action_codes=("edit",),
            ),
        ),
    )
    model = _by_key(release)["only-edit"]
    assert model.action_codes == ()
    assert model.derived_level is None
    assert release.blockers == (
        "active custom model only-edit has no effective actions",
        "custom model only-edit selects unavailable actions: edit",
    )


def test_inactive_model_keeps_selection_but_never_grants_actions() -> None:
    selection = CustomModelSelection(
        model_key="inactive",
        name="已停用",
        action_codes=("edit",),
        active=False,
    )
    release = derive_permission_models(
        _action_release(level_overrides={"edit": None}),
        custom_models=(selection,),
    )
    model = _by_key(release)["inactive"]
    assert model.selected_action_codes == ("edit",)
    assert model.action_codes == ()
    assert release.blockers == ()
    assert (
        effective_model_action_codes(
            model,
            _action_release(),
            "workflow",
        )
        == ()
    )


def test_shared_model_change_reports_all_grant_references_once() -> None:
    before = derive_permission_models(
        _action_release(),
        custom_models=(
            CustomModelSelection(
                model_key="shared",
                name="共享模型",
                action_codes=("edit",),
            ),
        ),
    )
    after = derive_permission_models(
        _action_release(),
        custom_models=(
            CustomModelSelection(
                model_key="shared",
                name="共享模型",
                action_codes=("edit", "share"),
            ),
        ),
    )
    impact = calculate_model_impact(
        before,
        after,
        grant_references={"shared": ("grant-3", "grant-1", "grant-2")},
    )
    assert impact.changed_model_keys == ("shared",)
    assert impact.affected_grant_refs == ("grant-1", "grant-2", "grant-3")


def test_model_delete_requires_inactive_unreferenced_custom() -> None:
    model = _by_key(
        derive_permission_models(
            _action_release(),
            custom_models=(
                CustomModelSelection(
                    model_key="retired",
                    name="待删除",
                    action_codes=("edit",),
                    active=False,
                ),
            ),
        )
    )["retired"]
    ensure_model_deletable(model, reference_count=0)
    with pytest.raises(ValueError, match="referenced"):
        ensure_model_deletable(model, reference_count=1)
    with pytest.raises(ValueError, match="inactive"):
        ensure_model_deletable(replace(model, active=True), reference_count=0)
    standard = _by_key(derive_permission_models(_action_release()))["viewer"]
    with pytest.raises(ValueError, match="standard"):
        ensure_model_deletable(standard, reference_count=0)


def test_preset_only_initializes_an_independent_selection() -> None:
    preset = ModelPreset(
        key="collaboration",
        name="协作编辑",
        action_codes=("edit", "rename"),
    )
    selection = initialize_from_preset(
        preset,
        model_key="custom-uuid",
        name="我的协作模型",
    )
    changed_preset = replace(preset, action_codes=("delete",))
    assert changed_preset.action_codes == ("delete",)
    assert selection.action_codes == ("edit", "rename")
    assert not hasattr(selection, "preset_key")
