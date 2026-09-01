"""Legacy model/action mapping contracts for F048."""

from __future__ import annotations

from bisheng.permission.migration.f048_model_mapper import (
    INITIAL_ACTION_LEVELS,
    LegacyPermissionModel,
    map_legacy_models,
)


def test_default_system_models_map_to_fixed_standard_identities():
    result = map_legacy_models(
        (
            LegacyPermissionModel(
                source_key="system-editor",
                name="Editor",
                relation="editor",
                permissions=(),
                is_system=True,
                permissions_explicit=False,
            ),
        )
    )

    assert result.standard_references == {"system-editor": "editor"}
    assert result.custom_models == ()
    assert result.blockers == ()


def test_edited_system_and_custom_models_keep_stable_keys_and_exact_actions():
    source = LegacyPermissionModel(
        source_key="system-manager",
        name="Edited manager",
        relation="manager",
        permissions=("view_app", "edit_app", "delete_app"),
        is_system=True,
        permissions_explicit=True,
    )
    custom = LegacyPermissionModel(
        source_key="custom-901",
        name="Download editor",
        relation=None,
        permissions=("download_file", "edit_file", "download_file"),
        active=None,
    )

    first = map_legacy_models((source, custom))
    second = map_legacy_models((source, custom))

    assert [row.model_key for row in first.custom_models] == [row.model_key for row in second.custom_models]
    edited = next(row for row in first.custom_models if row.legacy_source_key == "system-manager")
    mapped_custom = next(row for row in first.custom_models if row.legacy_source_key == "custom-901")
    assert edited.model_key.startswith("legacy-system-manager-")
    assert edited.action_codes == ("edit", "delete")
    assert mapped_custom.action_codes == ("edit", "download")
    assert mapped_custom.active is True
    assert mapped_custom.derived_level == 2


def test_edited_system_model_equal_to_standard_reuses_fixed_identity():
    result = map_legacy_models(
        (
            LegacyPermissionModel(
                source_key="owner",
                name="所有者",
                relation="owner",
                permissions=(
                    "manage_app_viewer",
                    "rename_file",
                    "edit_app",
                    "create_folder",
                    "upload_file",
                    "move_file",
                    "download_file",
                    "delete_app",
                    "share_app",
                    "use_app",
                    "publish_app",
                    "unpublish_app",
                ),
                is_system=True,
                permissions_explicit=True,
            ),
        )
    )

    assert result.standard_references == {"owner": "owner"}
    assert result.custom_models == ()
    assert result.blockers == ()


def test_view_only_model_preserves_visibility_without_granting_actions():
    result = map_legacy_models(
        (
            LegacyPermissionModel(
                source_key="view-only",
                name="View only",
                relation=None,
                permissions=("view_app",),
            ),
            LegacyPermissionModel(
                source_key="unknown",
                name="Unknown",
                relation=None,
                permissions=("launch_missiles",),
            ),
        )
    )

    view_only = next(row for row in result.custom_models if row.legacy_source_key == "view-only")
    assert view_only.action_codes == ()
    assert view_only.derived_level is None
    assert {item.difference_type for item in result.differences} == {
        "VISIBILITY_ONLY_MODEL_PRESERVED",
        "UNKNOWN_LEGACY_ACTION",
    }
    assert result.blockers == ("UNKNOWN_LEGACY_ACTION",)


def test_legacy_manage_tiers_expand_implications_and_clamp_above_model_level():
    source = LegacyPermissionModel(
        source_key="legacy-manager",
        name="Legacy manager",
        relation="manager",
        permissions=(
            "edit_app",
            "manage_app_owner",
            "manage_app_manager",
            "manage_app_viewer",
        ),
    )

    result = map_legacy_models((source,))

    mapped = result.custom_models[0]
    assert mapped.derived_level == 3
    assert mapped.allow_same_level is True
    assert result.blockers == ()
    assert [row.difference_type for row in result.differences] == ["MANAGE_SCOPE_CLAMPED_TO_MODEL_LEVEL"]


def test_manage_boundary_is_inferred_only_for_a_contiguous_non_expanding_set():
    lower_only = LegacyPermissionModel(
        source_key="manager-lower",
        name="Manager lower",
        relation=None,
        permissions=("edit_app", "manage_app_viewer"),
        grantable_relations=("viewer", "editor"),
    )
    same_level = LegacyPermissionModel(
        source_key="manager-same",
        name="Manager same",
        relation=None,
        permissions=("edit_app", "manage_app_viewer", "manage_app_editor"),
        grantable_relations=("viewer", "editor", "manager"),
    )
    gap = LegacyPermissionModel(
        source_key="manager-gap",
        name="Manager gap",
        relation=None,
        permissions=("edit_app", "manage_app_owner"),
        grantable_relations=("owner",),
    )

    result = map_legacy_models((lower_only, same_level, gap))

    by_source = {row.legacy_source_key: row for row in result.custom_models}
    assert by_source["manager-lower"].allow_same_level is False
    assert by_source["manager-same"].allow_same_level is True
    assert "manager-gap" not in by_source
    assert "NON_CONTIGUOUS_MANAGE_BOUNDARY" in result.blockers


def test_action_release_is_complete_scoped_and_uses_spec_initial_levels():
    result = map_legacy_models(())

    assert {row.code for row in result.action_release.actions} == set(INITIAL_ACTION_LEVELS)
    assert all(row.resource_types for row in result.action_release.actions)
    assert {row.code: row.level for row in result.action_release.actions} == INITIAL_ACTION_LEVELS
