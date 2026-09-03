"""F048 Grant source identity and reference-count contracts.

覆盖 AC: AC-15, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25,
AC-26, AC-27, AC-164, AC-166, AC-167
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from bisheng.common.errcode.permission import PermissionModelStateConflictError
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)


def _grant(
    grant_id: str,
    model_key: str,
    actions: tuple[str, ...],
    *,
    active: bool = False,
    model_active: bool = True,
):
    return GrantSnapshot(
        grant_id=grant_id,
        tenant_id=7,
        resource_type="workflow",
        resource_id="42",
        model=GrantModelSnapshot(
            model_key=model_key,
            active=model_active,
            action_codes=actions,
        ),
        active=active,
        sources=(),
    )


def test_one_resource_model_grant_is_reused_and_duplicate_add_is_idempotent() -> None:
    service = GrantSourceService()
    source = service.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="100",
        source_type="DIRECT",
    )
    result = service.add_source(_grant("g-editor", "editor", ("edit",)), source)
    assert result.grant.active is True
    assert len(result.grant.sources) == 1
    assert [(row.action, row.relation) for row in result.deltas] == [
        ("WRITE", "model"),
        ("WRITE", "grant"),
        ("WRITE", "ordinary_assignee"),
    ]

    repeated = service.add_source(result.grant, source)
    assert repeated.idempotent is True
    assert repeated.grant == result.grant
    assert repeated.deltas == ()


def test_direct_department_group_and_other_sources_remain_independent_usersets() -> None:
    service = GrantSourceService()
    sources = (
        service.canonicalize_source(
            source_id=1,
            subject_type="user",
            subject_id="100",
            source_type="DIRECT",
        ),
        service.canonicalize_source(
            source_id=2,
            subject_type="department",
            subject_id="17",
            include_children=True,
            source_type="DEPARTMENT",
        ),
        service.canonicalize_source(
            source_id=3,
            subject_type="user_group",
            subject_id="8",
            userset_relation="admin",
            source_type="USER_GROUP",
        ),
        service.canonicalize_source(
            source_id=4,
            subject_type="user",
            subject_id="101",
            source_type="OTHER",
            source_ref="external:ticket:99",
        ),
    )
    grant = _grant("g-manager", "manager", ("edit", "share"))
    for source in sources:
        grant = service.add_source(grant, source).grant

    assert [row.projected_subject for row in grant.sources] == [
        "user:100",
        "department:17#subtree_member",
        "user_group:8#admin",
        "user:101",
    ]
    assert len(grant.sources) == 4
    assert {row.source_type for row in grant.sources} == {
        "DIRECT",
        "DEPARTMENT",
        "USER_GROUP",
        "OTHER",
    }


def test_projected_subject_tuple_uses_reference_count_for_precise_revoke() -> None:
    service = GrantSourceService()
    direct = service.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="100",
        source_type="DIRECT",
    )
    membership = service.canonicalize_source(
        source_id=2,
        subject_type="user",
        subject_id="100",
        source_type="SPACE_MEMBERSHIP",
        source_ref="573",
    )
    first = service.add_source(
        _grant("g-viewer", "viewer", ("download",)),
        direct,
    )
    second = service.add_source(first.grant, membership)
    assert second.deltas == ()

    remove_direct = service.remove_source(second.grant, source_id=1)
    assert remove_direct.grant.active is True
    assert remove_direct.deltas == ()
    remove_last = service.remove_source(remove_direct.grant, source_id=2)
    assert remove_last.grant.active is False
    assert [(row.action, row.relation) for row in remove_last.deltas] == [
        ("DELETE", "ordinary_assignee"),
        ("DELETE", "grant"),
        ("DELETE", "model"),
    ]


def test_different_models_coexist_and_effective_actions_are_a_union() -> None:
    service = GrantSourceService()
    user = service.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="100",
        source_type="DIRECT",
    )
    department = service.canonicalize_source(
        source_id=2,
        subject_type="department",
        subject_id="17",
        source_type="DEPARTMENT",
    )
    editor = service.add_source(
        _grant("g-editor", "editor", ("edit",)),
        user,
    ).grant
    viewer = service.add_source(
        _grant("g-viewer", "viewer", ("download",)),
        department,
    ).grant
    assert service.effective_action_union(
        (editor, viewer),
        projected_subjects=frozenset({"user:100", "department:17#member"}),
    ) == ("download", "edit")

    inactive = replace(
        viewer,
        model=replace(viewer.model, active=False),
    )
    assert service.effective_action_union(
        (editor, inactive),
        projected_subjects=frozenset({"user:100", "department:17#member"}),
    ) == ("download", "edit")


def test_inactive_source_model_keeps_existing_binding_and_allows_precise_revoke() -> None:
    service = GrantSourceService()
    direct = service.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="100",
        source_type="DIRECT",
    )
    membership = service.canonicalize_source(
        source_id=2,
        subject_type="user",
        subject_id="100",
        source_type="SPACE_MEMBERSHIP",
        source_ref="573",
    )
    grant = service.add_source(
        _grant("g-custom", "custom", ("download",)),
        direct,
    ).grant
    grant = service.add_source(grant, membership).grant
    inactive = replace(grant, model=replace(grant.model, active=False))

    assert service.effective_action_union(
        (inactive,),
        projected_subjects=frozenset({"user:100"}),
    ) == ("download",)
    first_revoke = service.remove_source(inactive, source_id=1)
    assert first_revoke.deltas == ()
    last_revoke = service.remove_source(first_revoke.grant, source_id=2)
    assert last_revoke.grant.active is False
    assert [row.action for row in last_revoke.deltas] == ["DELETE", "DELETE", "DELETE"]


def test_remove_one_source_does_not_remove_other_model_or_source() -> None:
    service = GrantSourceService()
    direct = service.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="100",
        source_type="DIRECT",
    )
    department = service.canonicalize_source(
        source_id=2,
        subject_type="department",
        subject_id="17",
        source_type="DEPARTMENT",
    )
    grant = service.add_source(
        _grant("g-manager", "manager", ("edit", "share")),
        direct,
    ).grant
    grant = service.add_source(grant, department).grant
    removed = service.remove_source(grant, source_id=1)
    assert [row.source_id for row in removed.grant.sources] == [2]
    assert removed.grant.active is True
    assert [(row.action, row.user) for row in removed.deltas] == [("DELETE", "user:100")]


def test_move_source_updates_only_old_and_new_model_reference_sets() -> None:
    service = GrantSourceService()
    source = service.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="100",
        source_type="DIRECT",
    )
    old_grant = service.add_source(
        _grant("g-editor", "editor", ("edit",)),
        source,
    ).grant
    target_grant = _grant("g-manager", "manager", ("edit", "share"))
    moved = service.move_source(
        old_grant,
        target_grant,
        source_id=1,
    )
    assert moved.source_grant.active is False
    assert moved.target_grant.active is True
    assert moved.target_grant.sources[0].source_id == 1
    assert moved.target_grant.sources[0].version == 2
    assert len(moved.deltas) == 6


def test_ordinary_and_protected_same_user_have_separate_relations() -> None:
    service = GrantSourceService()
    ordinary = service.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="100",
        source_type="DIRECT",
    )
    protected = service.canonicalize_source(
        source_id=2,
        subject_type="user",
        subject_id="100",
        source_type="CREATOR",
        source_ref="workflow:42",
        protected=True,
    )
    first = service.add_source(
        _grant("g-owner", "owner", ("delete",)),
        ordinary,
    )
    second = service.add_source(first.grant, protected)
    assert [(row.action, row.relation) for row in second.deltas] == [("WRITE", "protected_assignee")]
    removed = service.remove_source(second.grant, source_id=1)
    assert removed.grant.active is True
    assert [(row.action, row.relation) for row in removed.deltas] == [("DELETE", "ordinary_assignee")]
    assert removed.grant.sources[0].protected is True


def test_inactive_model_rejects_new_source_fail_closed() -> None:
    service = GrantSourceService()
    source = service.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="100",
        source_type="DIRECT",
    )
    with pytest.raises(PermissionModelStateConflictError):
        service.add_source(
            _grant(
                "g-inactive",
                "custom",
                ("edit",),
                model_active=False,
            ),
            source,
        )
