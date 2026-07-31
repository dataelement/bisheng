"""Canonical parent and permission-mode migration contracts."""

from __future__ import annotations

from bisheng.permission.migration.f048_mode_mapper import map_resource_modes
from bisheng.permission.migration.f048_source_inventory import (
    PermissionMigrationResourceDTO,
)
from bisheng.permission.migration.f048_tuple_mapper import (
    MappedGrant,
    MappedGrantAssignee,
)


def _resource(
    resource_type: str,
    resource_id: str,
    *,
    tenant_id: int = 7,
    parent_type: str | None = None,
    parent_id: str | None = None,
) -> PermissionMigrationResourceDTO:
    return PermissionMigrationResourceDTO(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        status="ACTIVE",
        owner_user_id=11,
        ownership_kind="USER",
        source_locator=f"{resource_type}:{resource_id}",
        parent_type=parent_type,
        parent_id=parent_id,
    )


def _grant(
    resource_type: str,
    resource_id: str,
    *,
    protected: bool = False,
    source_key: str = "source-a",
) -> MappedGrant:
    assignee = MappedGrantAssignee(
        assignee_key=source_key,
        subject_type="user",
        subject_id="12",
        userset_relation=None,
        include_children=False,
        source_type="CREATOR" if protected else "DIRECT",
        source_ref=source_key,
        protected=protected,
        source_checksum=source_key,
    )
    return MappedGrant(
        grant_key=f"grant-{source_key}",
        tenant_id=7,
        resource_type=resource_type,
        resource_id=resource_id,
        model_key="editor",
        assignees=(assignee,),
    )


def test_space_and_library_are_always_custom_top_level_resources():
    resources = (
        _resource("knowledge_space", "1"),
        _resource("knowledge_library", "2"),
    )

    result = map_resource_modes(resources, ())

    assert {row.resource_key: row.mode for row in result.modes} == {
        "knowledge_space:1": "CUSTOM",
        "knowledge_library:2": "CUSTOM",
    }
    assert result.blockers == ()


def test_file_without_ordinary_local_grant_inherits_and_keeps_parent():
    resources = (
        _resource("knowledge_library", "1"),
        _resource(
            "knowledge_file",
            "2",
            parent_type="knowledge_library",
            parent_id="1",
        ),
    )

    result = map_resource_modes(
        resources,
        (_grant("knowledge_file", "2", protected=True),),
    )

    mode = next(row for row in result.modes if row.resource_key == "knowledge_file:2")
    assert mode.mode == "INHERIT"
    assert mode.parent_key == "knowledge_library:1"
    assert mode.ordinary_snapshot_assignee_keys == ()


def test_file_with_multiple_ordinary_sources_becomes_custom_with_snapshot():
    resources = (
        _resource("folder", "1", parent_type="knowledge_space", parent_id="9"),
        _resource(
            "knowledge_file",
            "2",
            parent_type="folder",
            parent_id="1",
        ),
        _resource("knowledge_space", "9"),
    )
    grants = (
        _grant("knowledge_file", "2", source_key="source-a"),
        _grant("knowledge_file", "2", source_key="source-b"),
    )

    result = map_resource_modes(resources, grants)

    mode = next(row for row in result.modes if row.resource_key == "knowledge_file:2")
    assert mode.mode == "CUSTOM"
    assert mode.parent_key == "folder:1"
    assert mode.ordinary_snapshot_assignee_keys == ("source-a", "source-b")


def test_missing_cross_tenant_and_cycle_parents_are_blockers():
    resources = (
        _resource(
            "folder",
            "missing",
            parent_type="knowledge_space",
            parent_id="404",
        ),
        _resource(
            "folder",
            "cross",
            parent_type="knowledge_space",
            parent_id="foreign",
        ),
        _resource("knowledge_space", "foreign", tenant_id=8),
        _resource("folder", "a", parent_type="folder", parent_id="b"),
        _resource("folder", "b", parent_type="folder", parent_id="a"),
    )

    result = map_resource_modes(resources, ())

    assert set(result.blockers) == {
        "CANONICAL_PARENT_CYCLE",
        "CROSS_TENANT_PARENT",
        "MISSING_CANONICAL_PARENT",
    }
    assert {row.resource_key for row in result.modes}.isdisjoint(
        {"folder:missing", "folder:cross", "folder:a", "folder:b"}
    )
