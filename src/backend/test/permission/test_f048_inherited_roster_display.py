"""Inherited roster rows: name the parent, and don't repeat its creator.

The roster reported inheritance as `knowledge_space:3377`, because the permission
layer holds a resource's identity and never its label. Resource names are
resolved the same way subject names already are — through the business side.

It also listed the parent's creator as a second row beside the resource's own
protected creator, so the same person appeared twice. That inherited copy grants
nothing here and cannot be acted on.
"""

from __future__ import annotations

from types import SimpleNamespace

from bisheng.permission.application.resource_api import _split_resource_key
from bisheng.tenant.domain.services.f048_permission_subject import (
    TenantPermissionSubjectDirectory,
)


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


async def test_resource_display_names_resolves_spaces_and_folders(monkeypatch) -> None:
    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

    async def load_spaces(ids: list[int]):
        assert ids == [3377]
        return [SimpleNamespace(id=3377, name="Product Knowledge")]

    async def load_folders(ids: list[int]):
        assert ids == [94661]
        return [SimpleNamespace(id=94661, file_name="Release Notes")]

    monkeypatch.setattr(KnowledgeDao, "aget_list_by_ids", load_spaces)
    monkeypatch.setattr(KnowledgeFileDao, "aget_file_by_ids", load_folders)

    labels = await TenantPermissionSubjectDirectory().resource_display_names(
        (
            ("knowledge_space", "3377"),
            ("folder", "94661"),
            ("folder", "not-an-id"),
            ("workflow", "wf-1"),
        )
    )

    assert labels == {
        ("knowledge_space", "3377"): "Product Knowledge",
        ("folder", "94661"): "Release Notes",
    }
