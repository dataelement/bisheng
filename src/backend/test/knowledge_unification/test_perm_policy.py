"""F118 Catalog pure-visibility policy. 覆盖 AC: AC-78, AC-80, AC-81, AC-82."""

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
    derive_permission_models,
    effective_model_action_codes,
)


def action_release():
    return derive_action_release(
        CatalogAction(
            code=code, name=code, level=1 if code == "download" else 2, resource_types=ACTION_RESOURCE_SCOPES[code]
        )
        for code in REGISTERED_ACTION_CODES
    )


def custom(selection):
    return next(
        model
        for model in derive_permission_models(action_release(), custom_models=(selection,)).models
        if model.model_key == selection.model_key
    )


def test_active_catalog_has_no_use_and_preserves_file_actions():
    assert "use" not in REGISTERED_ACTION_CODES
    assert "visible" not in REGISTERED_ACTION_CODES
    assert ACTION_RESOURCE_SCOPES["rename"] == {"folder", "knowledge_file"}
    assert not {"folder", "knowledge_file"} & ACTION_RESOURCE_SCOPES["edit"]
    with pytest.raises(ValueError, match="registered"):
        derive_action_release(
            (
                *action_release().actions,
                CatalogAction(code="use", name="Use", level=1, resource_types=frozenset({"tool"})),
            )
        )


def test_marked_empty_custom_preserves_original_tier_and_stable_key():
    model = custom(
        CustomModelSelection(
            "legacy-use", "Legacy", (), visibility_only_resource_types=("tool", "app"), visibility_level=3
        )
    )
    assert model.model_key == "legacy-use"
    assert model.action_codes == () and model.derived_level == 3
    assert model.visibility_only_resource_types == ("app", "tool")
    assert model.visibility_level == 3
    assert (
        derive_permission_models(
            action_release(),
            custom_models=(
                CustomModelSelection(
                    "legacy-use", "Legacy", (), visibility_only_resource_types=("tool",), visibility_level=3
                ),
            ),
        ).blockers
        == ()
    )


def test_global_download_can_remain_pure_visible_for_tool_only():
    model = custom(
        CustomModelSelection(
            "mixed", "Mixed", ("download",), visibility_only_resource_types=("tool",), visibility_level=3
        )
    )
    assert model.derived_level == 1 and model.visibility_level == 3
    assert effective_model_action_codes(model, action_release(), "tool") == ()
    assert effective_model_action_codes(model, action_release(), "knowledge_file") == ("download",)


def test_server_preserves_provenance_for_temporarily_concrete_types():
    model = custom(
        CustomModelSelection(
            "mixed",
            "Mixed",
            ("download",),
            visibility_only_resource_types=("tool", "knowledge_file"),
            visibility_level=3,
        )
    )
    assert model.visibility_only_resource_types == ("knowledge_file", "tool")


@pytest.mark.parametrize(
    "types,level",
    [
        (("unknown",), 1),
        (("tool", "tool"), 1),
        (("tool",), None),
        (("tool",), True),
        (("tool",), 0),
        (("tool",), 5),
        ((), 2),
    ],
)
def test_invalid_markers_are_rejected(types, level):
    with pytest.raises(ValueError, match="visibility"):
        custom(
            CustomModelSelection("invalid", "Invalid", (), visibility_only_resource_types=types, visibility_level=level)
        )


def test_unmarked_empty_model_remains_unusable():
    model = custom(CustomModelSelection("empty", "Empty", ()))
    assert model.derived_level is None and model.visibility_only_resource_types == ()


def test_fresh_standard_viewer_has_server_owned_pure_visible_types():
    viewer = next(model for model in derive_permission_models(action_release()).models if model.model_key == "viewer")
    assert {"tool", "app", "assistant", "workflow", "knowledge_space"} <= set(viewer.visibility_only_resource_types)
    assert viewer.visibility_level == 1
    assert viewer.derived_level == 1 and viewer.action_codes == ("download",)


def test_marker_and_original_tier_are_in_model_checksum():
    selection = CustomModelSelection(
        "legacy", "Legacy", (), visibility_only_resource_types=("tool",), visibility_level=1
    )
    releases = [
        derive_permission_models(action_release(), custom_models=(value,))
        for value in (
            selection,
            replace(selection, visibility_level=2),
            replace(selection, visibility_only_resource_types=("app",)),
        )
    ]
    assert len({release.checksum for release in releases}) == 3
