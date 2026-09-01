"""Legacy tuple/binding to F048 Grant mapping contracts."""

from __future__ import annotations

import pytest

from bisheng.permission.migration.f048_source_inventory import (
    LegacyTupleSource,
    PermissionMigrationResourceDTO,
)
from bisheng.permission.migration.f048_tuple_mapper import (
    LegacyGrantBinding,
    compile_department_child_mirrors,
    map_legacy_tuples,
)


def _tuple(
    *,
    user: str = "user:11",
    relation: str = "editor",
    object_key: str = "workflow:wf-1",
    tenant_id: int = 7,
) -> LegacyTupleSource:
    return LegacyTupleSource(
        tenant_id=tenant_id,
        user=user,
        relation=relation,
        object=object_key,
    )


def test_unbound_direct_tuple_uses_standard_model_fallback():
    result = map_legacy_tuples((_tuple(),), (), model_key_by_source={})

    assert result.blockers == ()
    assert len(result.grants) == 1
    grant = result.grants[0]
    assert grant.model_key == "editor"
    assert grant.resource_type == "workflow"
    assert grant.assignees[0].subject_type == "user"
    assert grant.assignees[0].source_type == "DIRECT"


def test_unique_binding_wins_and_preserves_provenance_and_protection():
    binding = LegacyGrantBinding(
        binding_key="binding-1",
        tenant_id=7,
        resource_type="workflow",
        resource_id="wf-1",
        relation="editor",
        model_source_key="custom-901",
        subject_type="user",
        subject_id="11",
        source_type="CREATOR",
        source_ref="workflow:wf-1:user:11",
        protected=True,
    )

    result = map_legacy_tuples(
        (_tuple(),),
        (binding,),
        model_key_by_source={"custom-901": "legacy-custom-901"},
    )

    assignee = result.grants[0].assignees[0]
    assert result.grants[0].model_key == "legacy-custom-901"
    assert assignee.source_type == "CREATOR"
    assert assignee.source_ref == "workflow:wf-1:user:11"
    assert assignee.protected is True


def test_department_subtree_userset_is_not_expanded():
    result = map_legacy_tuples(
        (
            _tuple(
                user="department:22#subtree_member",
                relation="viewer",
            ),
        ),
        (),
        model_key_by_source={},
    )

    assignee = result.grants[0].assignees[0]
    assert assignee.subject_type == "department"
    assert assignee.subject_id == "22"
    assert assignee.userset_relation == "subtree_member"
    assert assignee.include_children is True


def test_legacy_include_children_binding_normalizes_member_to_subtree():
    binding = LegacyGrantBinding(
        binding_key="binding-subtree",
        tenant_id=7,
        resource_type="workflow",
        resource_id="wf-1",
        relation="viewer",
        model_source_key="custom-viewer",
        subject_type="department",
        subject_id="22",
        include_children=True,
    )

    result = map_legacy_tuples(
        (
            _tuple(
                user="department:22#member",
                relation="viewer",
            ),
        ),
        (binding,),
        model_key_by_source={"custom-viewer": "custom-viewer"},
    )

    assert result.blockers == ()
    assignee = result.grants[0].assignees[0]
    assert assignee.subject_id == "22"
    assert assignee.userset_relation == "subtree_member"
    assert assignee.include_children is True


def test_legacy_expanded_department_children_are_retired_not_independent_grants():
    binding = LegacyGrantBinding(
        binding_key="binding-subtree",
        tenant_id=7,
        resource_type="workflow",
        resource_id="wf-1",
        relation="viewer",
        model_source_key="custom-viewer",
        subject_type="department",
        subject_id="22",
        include_children=True,
    )
    root = _tuple(
        user="department:22#member",
        relation="viewer",
    )
    child = _tuple(
        user="department:23#member",
        relation="viewer",
    )
    parent = LegacyTupleSource(
        tenant_id=None,
        user="department:22",
        relation="parent",
        object="department:23",
    )

    result = map_legacy_tuples(
        (root, child, parent),
        (binding,),
        model_key_by_source={"custom-viewer": "custom-viewer"},
    )

    assert result.blockers == ()
    assert len(result.grants) == 1
    assert len(result.grants[0].assignees) == 1
    assert result.grants[0].assignees[0].subject_id == "22"
    assert set(result.retired_tuple_keys) == {root.key, child.key}
    assert result.preserved_tuples == (parent,)


def test_multiple_models_and_sources_are_retained_without_highest_model_flattening():
    tuples = (
        _tuple(user="user:11", relation="editor"),
        _tuple(user="department:22#member", relation="viewer"),
    )
    bindings = (
        LegacyGrantBinding(
            binding_key="binding-a",
            tenant_id=7,
            resource_type="workflow",
            resource_id="wf-1",
            relation="editor",
            model_source_key="custom-edit",
            subject_type="user",
            subject_id="11",
        ),
        LegacyGrantBinding(
            binding_key="binding-b",
            tenant_id=7,
            resource_type="workflow",
            resource_id="wf-1",
            relation="viewer",
            model_source_key="custom-download",
            subject_type="department",
            subject_id="22",
            userset_relation="member",
        ),
    )

    result = map_legacy_tuples(
        tuples,
        bindings,
        model_key_by_source={
            "custom-edit": "edit-only",
            "custom-download": "download-only",
        },
    )

    assert {grant.model_key for grant in result.grants} == {
        "edit-only",
        "download-only",
    }
    assert len(result.retired_tuple_keys) == 2


def test_duplicate_tuple_is_idempotently_deduplicated():
    source = _tuple()
    result = map_legacy_tuples(
        (source, source),
        (),
        model_key_by_source={},
    )

    assert len(result.grants) == 1
    assert len(result.grants[0].assignees) == 1
    assert result.deduplicated_count == 1


def test_direct_and_membership_sources_share_grant_but_keep_provenance():
    tuples = (
        _tuple(user="user:11", relation="viewer"),
        _tuple(user="user:11", relation="editor"),
    )
    bindings = (
        LegacyGrantBinding(
            binding_key="direct-binding",
            tenant_id=7,
            resource_type="workflow",
            resource_id="wf-1",
            relation="viewer",
            model_source_key="custom-combined",
            subject_type="user",
            subject_id="11",
            source_type="DIRECT",
            source_ref="direct:11",
        ),
        LegacyGrantBinding(
            binding_key="membership-binding",
            tenant_id=7,
            resource_type="workflow",
            resource_id="wf-1",
            relation="editor",
            model_source_key="custom-combined",
            subject_type="user",
            subject_id="11",
            source_type="SPACE_MEMBERSHIP",
            source_ref="membership:99",
        ),
    )

    result = map_legacy_tuples(
        tuples,
        bindings,
        model_key_by_source={"custom-combined": "custom-combined"},
    )

    assert len(result.grants) == 1
    assert len(result.grants[0].assignees) == 2
    assert {row.source_type for row in result.grants[0].assignees} == {
        "DIRECT",
        "SPACE_MEMBERSHIP",
    }
    assert len({row.source_checksum for row in result.grants[0].assignees}) == 2


def test_system_shared_and_parent_facts_are_preserved_not_converted_to_grants():
    tuples = (
        _tuple(user="system:public", relation="shared_with"),
        _tuple(
            user="knowledge_space:1",
            relation="parent",
            object_key="folder:2",
        ),
    )

    result = map_legacy_tuples(tuples, (), model_key_by_source={})

    assert result.grants == ()
    assert {row.relation for row in result.preserved_tuples} == {
        "shared_with",
        "parent",
    }
    assert result.retired_tuple_keys == ()


def test_department_parent_facts_compile_symmetric_child_mirrors():
    mirrors = compile_department_child_mirrors(
        (
            _tuple(
                user="department:10",
                relation="parent",
                object_key="department:20",
            ),
            _tuple(
                user="department:20",
                relation="parent",
                object_key="department:30",
            ),
        )
    )

    assert mirrors == (
        {
            "user": "department:20",
            "relation": "child",
            "object": "department:10",
        },
        {
            "user": "department:30",
            "relation": "child",
            "object": "department:20",
        },
    )


@pytest.mark.parametrize(
    "tuples",
    (
        (
            _tuple(
                user="department:10",
                relation="parent",
                object_key="department:10",
            ),
        ),
        (
            _tuple(
                user="department:10",
                relation="parent",
                object_key="department:20",
            ),
            _tuple(
                user="department:20",
                relation="parent",
                object_key="department:10",
            ),
        ),
        (
            _tuple(
                user="department:10",
                relation="parent",
                object_key="department:20",
            ),
            _tuple(
                user="department:11",
                relation="parent",
                object_key="department:20",
            ),
        ),
    ),
)
def test_invalid_department_parent_topology_blocks_child_compilation(
    tuples,
):
    with pytest.raises(ValueError):
        compile_department_child_mirrors(tuples)


def test_conflicting_or_missing_binding_model_blocks_without_fallback():
    source = _tuple()
    base = {
        "tenant_id": 7,
        "resource_type": "workflow",
        "resource_id": "wf-1",
        "relation": "editor",
        "subject_type": "user",
        "subject_id": "11",
    }
    result = map_legacy_tuples(
        (source,),
        (
            LegacyGrantBinding(
                binding_key="one",
                model_source_key="missing-a",
                **base,
            ),
            LegacyGrantBinding(
                binding_key="two",
                model_source_key="missing-b",
                **base,
            ),
        ),
        model_key_by_source={},
    )

    assert result.grants == ()
    assert result.blockers == ("CONFLICTING_BINDINGS",)


def test_binding_without_direct_root_tuple_is_an_audited_noop():
    binding = LegacyGrantBinding(
        binding_key="orphan-binding",
        tenant_id=7,
        resource_type="workflow",
        resource_id="wf-1",
        relation="viewer",
        model_source_key="custom-viewer",
        subject_type="department",
        subject_id="22",
        include_children=True,
    )

    result = map_legacy_tuples(
        (),
        (binding,),
        model_key_by_source={"custom-viewer": "custom-viewer"},
    )

    assert result.grants == ()
    assert result.blockers == ()
    assert result.differences[0].tuple_key == "binding:orphan-binding"
    assert result.differences[0].severity == "INFO"


def test_business_creator_becomes_protected_owner_and_divergent_owner_is_retained():
    resource = PermissionMigrationResourceDTO(
        tenant_id=7,
        resource_type="channel",
        resource_id="channel-1",
        status="ACTIVE",
        owner_user_id=12,
        ownership_kind="USER",
        source_locator="channel:channel-1",
        creator_user_ids=(11,),
    )

    result = map_legacy_tuples(
        (
            _tuple(
                user="user:11",
                relation="owner",
                object_key="channel:channel-1",
            ),
        ),
        (),
        model_key_by_source={},
        resources=(resource,),
    )

    grant = result.grants[0]
    assert grant.model_key == "owner"
    assert {(row.subject_id, row.protected, row.source_type) for row in grant.assignees} == {
        ("11", True, "CREATOR"),
        ("12", False, "DIRECT"),
    }
    assert result.blockers == ()
    assert any(
        row.difference_type == "OWNER_FACT_DIVERGENCE_PRESERVED" and row.severity == "INFO"
        for row in result.differences
    )


@pytest.mark.parametrize("resource_type", ["channel", "knowledge_space"])
def test_private_resource_retires_legacy_grants_and_keeps_only_creator(resource_type):
    resource = PermissionMigrationResourceDTO(
        tenant_id=7,
        resource_type=resource_type,
        resource_id="private-1",
        status="ACTIVE",
        owner_user_id=12,
        ownership_kind="USER",
        source_locator=f"{resource_type}:private-1",
        creator_user_ids=(11,),
        migrate_ordinary_grants=False,
    )
    binding = LegacyGrantBinding(
        binding_key="private-manager",
        tenant_id=7,
        resource_type=resource_type,
        resource_id="private-1",
        relation="manager",
        model_source_key="manager",
        subject_type="user",
        subject_id="99",
    )
    source = _tuple(
        user="user:99",
        relation="manager",
        object_key=f"{resource_type}:private-1",
    )

    result = map_legacy_tuples(
        (source,),
        (binding,),
        model_key_by_source={"manager": "manager"},
        resources=(resource,),
    )

    assert len(result.grants) == 1
    assert result.grants[0].model_key == "owner"
    assert [(row.subject_id, row.protected) for row in result.grants[0].assignees] == [("11", True)]
    assert result.retired_tuple_keys == (source.key,)
    assert result.blockers == ()
    assert {row.difference_type for row in result.differences} == {"PRIVATE_RESOURCE_GRANT_RETIRED"}


def test_non_f048_resource_tuple_remains_store_scoped_and_is_not_retired():
    source = LegacyTupleSource(
        tenant_id=None,
        user="user:7",
        relation="owner",
        object="llm_model:legacy-1",
    )

    result = map_legacy_tuples(
        (source,),
        (),
        model_key_by_source={},
    )

    assert result.blockers == ()
    assert result.grants == ()
    assert result.preserved_tuples == (source,)
    assert result.retired_tuple_keys == ()
