"""F034 — unit tests for the relation-model move-permission backfill (pure transform)."""

from bisheng.permission.domain.relation_model_backfill import (
    apply_move_permission_backfill,
    target_new_permissions,
)

_MOVE = {"move_file", "move_folder"}


def _model(model_id, relation, *, is_system=True, explicit=True, permissions=None):
    return {
        "id": model_id,
        "name": model_id,
        "relation": relation,
        "is_system": is_system,
        "permissions_explicit": explicit,
        "permissions": list(permissions or []),
    }


def test_target_per_tier():
    assert target_new_permissions("owner") == _MOVE
    assert target_new_permissions("manager") == _MOVE
    assert target_new_permissions("editor") == _MOVE
    assert target_new_permissions("viewer") == set()


def test_frozen_owner_manager_editor_get_both_viewer_none():
    models = [
        _model("owner", "owner", permissions=["view_space"]),
        _model("manager", "manager", permissions=[]),
        _model("editor", "editor", permissions=["upload_file"]),
        _model("viewer", "viewer", permissions=["view_file"]),
    ]
    updated, changes = apply_move_permission_backfill(models)
    by_id = {m["id"]: set(m["permissions"]) for m in updated}
    assert _MOVE <= by_id["owner"] and "view_space" in by_id["owner"]
    assert _MOVE <= by_id["manager"]
    assert _MOVE <= by_id["editor"] and "upload_file" in by_id["editor"]
    assert by_id["viewer"] == {"view_file"}  # viewer untouched
    assert {c["id"] for c in changes} == {"owner", "manager", "editor"}


def test_dynamic_and_custom_models_skipped():
    models = [
        _model("editor", "editor", explicit=False, permissions=[]),  # dynamic → skip
        _model("cust", "editor", is_system=False, permissions=["view_file"]),  # custom → skip
    ]
    updated, changes = apply_move_permission_backfill(models)
    assert changes == []
    assert set(updated[0]["permissions"]) == set()
    assert set(updated[1]["permissions"]) == {"view_file"}


def test_idempotent():
    models = [_model("owner", "owner", permissions=["view_space"])]
    once, _ = apply_move_permission_backfill(models)
    twice, changes = apply_move_permission_backfill(once)
    assert changes == []
    assert twice == once


def test_only_missing_added_never_removed():
    # owner already has move_file but not move_folder → only the missing one is added
    models = [_model("owner", "owner", permissions=["view_space", "move_file", "share_file"])]
    updated, changes = apply_move_permission_backfill(models)
    assert changes[0]["added"] == ["move_folder"]
    assert {"view_space", "move_file", "move_folder", "share_file"} <= set(updated[0]["permissions"])
