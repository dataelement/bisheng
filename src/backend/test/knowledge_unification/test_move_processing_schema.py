"""T930: one Domain DTO family, no SQL or hash/control-plane implementation."""

import ast
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from bisheng.knowledge.domain.schemas import move_processing as schema


@pytest.mark.parametrize("kind,key", [("space", 1), ("file", 0), ("folder", True), ("file", "1")])
def test_move_root_has_concrete_closed_identity(kind, key):
    with pytest.raises(ValueError):
        schema.MoveRoot(kind, key)


def test_public_reexports_are_the_exact_same_classes():
    from bisheng.knowledge.domain.repositories import move_scope_repository as repository

    for name in ("MoveRoot", "MoveRow", "MoveLeaf", "MoveParentChange", "MoveScope"):
        assert getattr(repository, name) is getattr(schema, name)
        assert getattr(schema, name).__dataclass_params__.frozen
        assert hasattr(getattr(schema, name), "__slots__")


def test_parent_change_has_original_eight_fields_and_no_authority_flag():
    row = schema.MoveParentChange("knowledge_file", 81, "folder", 50, "folder", 51, "CUSTOM", 4)
    assert [item.name for item in fields(row)] == [
        "resource_type",
        "resource_id",
        "old_parent_type",
        "old_parent_id",
        "new_parent_type",
        "new_parent_id",
        "mode",
        "expected_permission_version",
    ]
    with pytest.raises(FrozenInstanceError):
        row.mode = "INHERIT"
    with pytest.raises(ValueError):
        schema.MoveParentChange("knowledge_file", 81, "folder", 50, "folder", 51, "CUSTOM", True)


def test_schema_never_calculates_a_digest_or_opens_business_control_plane():
    tree = ast.parse(Path(schema.__file__).read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not any(
        "repositories" in name
        or "application" in name
        or "sqlalchemy" in name
        or "sqlmodel" in name
        or "hashlib" in name
        for name in imports
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("execute", "commit", "flush", "sha256")
        for node in ast.walk(tree)
    )
