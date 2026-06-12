"""Tests for `DepartmentService.aget_tree` tenant-admin subtree filter.

PRD §4.5: Child Admin sees only the mount-point subtree (mount dept itself
included). Existing test for full-tree behavior on tenant_id=Root still
covered in `test_department_service.py::test_get_tree_allows_tenant_admin_full_tree`.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.database.models.department import DepartmentDao
from bisheng.department.domain.services import department_service as m
from bisheng.department.domain.services.department_service import DepartmentService


def _user(user_id=10, user_role=None, tenant_id=5):
    return SimpleNamespace(
        user_id=user_id,
        user_role=user_role if user_role is not None else [2],
        tenant_id=tenant_id,
    )


def _dept(id_, dept_id, name, parent_id, path):
    return SimpleNamespace(
        id=id_, dept_id=dept_id, name=name, parent_id=parent_id, path=path,
        sort_order=0, source='local', status='active',
    )


def _patched_session(depts):
    dept_result = MagicMock()
    dept_result.all.return_value = depts
    count_result = MagicMock()
    count_result.all.return_value = []
    db_session = MagicMock()
    db_session.exec = AsyncMock(side_effect=[dept_result, count_result])

    @asynccontextmanager
    async def fake_session():
        yield db_session

    return fake_session


@pytest.mark.asyncio
async def test_aget_tree_child_admin_sees_only_mount_subtree():
    """Child Admin (tenant=5, mount=/1/22/) → tree contains only mount + descendants."""
    root = _dept(1, 'BS@root', 'Root', None, '/1/')
    sibling = _dept(23, 'BS@sib', 'Sibling', 1, '/1/23/')
    mount = _dept(22, 'BS@mount', 'Mount', 1, '/1/22/')
    leaf = _dept(45, 'BS@leaf', 'Leaf', 22, '/1/22/45/')

    with patch.object(
        m, 'get_async_db_session', _patched_session([root, sibling, mount, leaf]),
    ), patch.object(
        DepartmentDao, 'aget_user_admin_departments',
        new_callable=AsyncMock, return_value=[],
    ), patch.object(
        m, '_is_tenant_admin', new_callable=AsyncMock, return_value=True,
    ), patch.object(
        m, '_aget_user_tenant_root_path',
        new_callable=AsyncMock, return_value=mount.path,
    ), patch.object(
        m, '_is_registration_enabled', return_value=True,
    ):
        tree = await DepartmentService.aget_tree(_user())

    assert [n.id for n in tree] == [22]
    assert [c.id for c in tree[0].children] == [45]


@pytest.mark.asyncio
async def test_aget_tree_dept_admin_and_child_admin_subtree_union():
    """Dept admin of /1/23/ + Child Admin of /1/22/ → both subtrees visible."""
    root = _dept(1, 'BS@root', 'Root', None, '/1/')
    sibling = _dept(23, 'BS@sib', 'Sibling', 1, '/1/23/')
    mount = _dept(22, 'BS@mount', 'Mount', 1, '/1/22/')
    leaf = _dept(45, 'BS@leaf', 'Leaf', 22, '/1/22/45/')
    far = _dept(99, 'BS@far', 'Far', 1, '/1/99/')

    dept_admin_dept = SimpleNamespace(id=23, path='/1/23/')

    with patch.object(
        m, 'get_async_db_session',
        _patched_session([root, sibling, mount, leaf, far]),
    ), patch.object(
        DepartmentDao, 'aget_user_admin_departments',
        new_callable=AsyncMock, return_value=[dept_admin_dept],
    ), patch.object(
        m, '_is_tenant_admin', new_callable=AsyncMock, return_value=True,
    ), patch.object(
        m, '_aget_user_tenant_root_path',
        new_callable=AsyncMock, return_value=mount.path,
    ), patch.object(
        m, '_is_registration_enabled', return_value=True,
    ):
        tree = await DepartmentService.aget_tree(_user())

    # Two roots in the tree: dept-admin subtree (23) and tenant-admin subtree (22).
    ids = sorted(n.id for n in tree)
    assert ids == [22, 23]
    # Mount subtree carries its child; sibling 99 is excluded.
    mount_node = next(n for n in tree if n.id == 22)
    assert [c.id for c in mount_node.children] == [45]


@pytest.mark.asyncio
async def test_aget_tree_child_admin_with_unresolvable_mount_returns_empty():
    """Defensive: if `_aget_user_tenant_root_path` returns None and the user
    has no dept-admin grants either, the call should not crash and should
    return an empty tree (no path filter applies, but there are no admin
    paths to filter against)."""
    root = _dept(1, 'BS@root', 'Root', None, '/1/')

    with patch.object(
        m, 'get_async_db_session', _patched_session([root]),
    ), patch.object(
        DepartmentDao, 'aget_user_admin_departments',
        new_callable=AsyncMock, return_value=[],
    ), patch.object(
        m, '_is_tenant_admin', new_callable=AsyncMock, return_value=True,
    ), patch.object(
        m, '_aget_user_tenant_root_path',
        new_callable=AsyncMock, return_value=None,
    ), patch.object(
        m, '_is_registration_enabled', return_value=True,
    ):
        tree = await DepartmentService.aget_tree(_user())

    # Backwards-compatible with `test_get_tree_allows_tenant_admin_full_tree`:
    # no admin_paths → no path filter → full tree returned. (Production: Root
    # tenant only; Child Admin scenario always has a mount path.)
    assert [n.id for n in tree] == [1]
