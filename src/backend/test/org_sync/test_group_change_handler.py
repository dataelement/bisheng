"""Unit tests for GroupChangeHandler (F003).

Pure Python tests — no database or async needed.
"""

from bisheng.permission.application import (
    PermissionObject,
    PermissionRelation,
    PermissionRelationChange,
    PermissionSubject,
)
from bisheng.user_group.domain.services.group_change_handler import GroupChangeHandler


def _change(action: str, *, user_id: int, relation: str) -> PermissionRelationChange:
    return PermissionRelationChange(
        action=action,
        relation=PermissionRelation(
            subject=PermissionSubject("user", str(user_id)),
            relation=relation,
            resource=PermissionObject("user_group", "5"),
        ),
    )


def test_on_created():
    ops = GroupChangeHandler.on_created(group_id=5, creator_user_id=1)
    assert len(ops) == 1
    assert ops[0] == _change("grant", user_id=1, relation="admin")


def test_on_deleted():
    ops = GroupChangeHandler.on_deleted(group_id=5)
    assert ops == []


def test_on_members_added():
    ops = GroupChangeHandler.on_members_added(group_id=5, user_ids=[3, 7, 11])
    assert len(ops) == 3
    assert ops == [
        _change("grant", user_id=3, relation="member"),
        _change("grant", user_id=7, relation="member"),
        _change("grant", user_id=11, relation="member"),
    ]


def test_on_member_removed():
    ops = GroupChangeHandler.on_member_removed(group_id=5, user_id=3)
    assert len(ops) == 1
    assert ops[0] == _change("revoke", user_id=3, relation="member")


def test_on_admin_set():
    ops = GroupChangeHandler.on_admin_set(group_id=5, user_ids=[1, 9])
    assert len(ops) == 2
    assert ops == [
        _change("grant", user_id=1, relation="admin"),
        _change("grant", user_id=9, relation="admin"),
    ]


def test_on_admin_removed():
    ops = GroupChangeHandler.on_admin_removed(group_id=5, user_ids=[1, 9])
    assert len(ops) == 2
    assert ops == [
        _change("revoke", user_id=1, relation="admin"),
        _change("revoke", user_id=9, relation="admin"),
    ]


def test_execute_stub_no_error():
    ops = GroupChangeHandler.on_members_added(group_id=1, user_ids=[2, 3])
    GroupChangeHandler.execute(ops)  # Should not raise


def test_execute_empty_no_error():
    GroupChangeHandler.execute([])  # Should not raise
