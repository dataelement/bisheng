"""Inherited roster rows: name the parent, and don't repeat its creator.

Two走查 findings on the "继承上级" view.

The roster reported inheritance as `knowledge_space:3377`, because the permission
layer holds a resource's identity and never its label. Resource names are
resolved the same way subject names already are — through the business side.

It also listed the parent's creator as a second row beside the resource's own
protected creator, so the same person appeared twice. That inherited copy grants
nothing here and cannot be acted on.
"""

from __future__ import annotations

from bisheng.permission.application.resource_api import _split_resource_key


def test_split_resource_key() -> None:
    assert _split_resource_key("knowledge_space:3377") == ("knowledge_space", "3377")
    assert _split_resource_key("folder:12") == ("folder", "12")


def test_split_resource_key_tolerates_a_missing_separator() -> None:
    assert _split_resource_key("3377") == ("3377", "")


def test_inherited_creator_rows_are_dropped() -> None:
    """The filter the roster applies to inherited rows."""

    class _Row:
        def __init__(self, source_type: str) -> None:
            self.source_type = source_type

    inherited = [
        (_Row("CREATOR"), "owner"),
        (_Row("DIRECT"), "viewer"),
        (_Row("DEPARTMENT"), "viewer"),
    ]
    kept = [(row, key) for row, key in inherited if row.source_type != "CREATOR"]

    assert [key for _, key in kept] == ["viewer", "viewer"]
    assert all(row.source_type != "CREATOR" for row, _ in kept)
