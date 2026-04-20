"""Unit tests for GroupChangeHandler (F003).

Pure Python tests — no database or async needed.
"""

from bisheng.user_group.domain.services.group_change_handler import (
    GroupChangeHandler,
    TupleOperation,
)


def test_on_created():
    ops = GroupChangeHandler.on_created(group_id=5, creator_user_id=1)
    assert len(ops) == 1
    assert ops[0] == TupleOperation(
        action='write', user='user:1', relation='admin', object='user_group:5',
    )


def test_on_deleted():
    ops = GroupChangeHandler.on_deleted(group_id=5)
    assert ops == []


def test_on_members_added():
    ops = GroupChangeHandler.on_members_added(group_id=5, user_ids=[3, 7, 11])
    assert len(ops) == 3
    assert ops[0] == TupleOperation(
        action='write', user='user:3', relation='member', object='user_group:5',
    )
    assert ops[1] == TupleOperation(
        action='write', user='user:7', relation='member', object='user_group:5',
    )
    assert ops[2] == TupleOperation(
        action='write', user='user:11', relation='member', object='user_group:5',
    )


def test_on_member_removed():
    ops = GroupChangeHandler.on_member_removed(group_id=5, user_id=3)
    assert len(ops) == 1
    assert ops[0] == TupleOperation(
        action='delete', user='user:3', relation='member', object='user_group:5',
    )


def test_on_admin_set():
    ops = GroupChangeHandler.on_admin_set(group_id=5, user_ids=[1, 9])
    assert len(ops) == 2
    assert ops[0] == TupleOperation(
        action='write', user='user:1', relation='admin', object='user_group:5',
    )
    assert ops[1] == TupleOperation(
        action='write', user='user:9', relation='admin', object='user_group:5',
    )


def test_on_admin_removed():
    ops = GroupChangeHandler.on_admin_removed(group_id=5, user_ids=[1, 9])
    assert len(ops) == 2
    assert ops[0] == TupleOperation(
        action='delete', user='user:1', relation='admin', object='user_group:5',
    )
    assert ops[1] == TupleOperation(
        action='delete', user='user:9', relation='admin', object='user_group:5',
    )


def test_execute_stub_no_error():
    ops = GroupChangeHandler.on_members_added(group_id=1, user_ids=[2, 3])
    GroupChangeHandler.execute(ops)  # Should not raise


def test_execute_empty_no_error():
    GroupChangeHandler.execute([])  # Should not raise
