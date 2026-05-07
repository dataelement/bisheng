"""Regression tests for ``/user/update`` and ``/user/list`` permission gates.

Two analogous bugs lived in ``bisheng/user/api/user.py``: both endpoints
checked super-admin / user-group admin / department-admin but completely
ignored the ``tenant#admin`` FGA tuple. The Authorization Model does not
inherit ``tenant#admin`` into ``department#admin``, so a Child Tenant admin
fell through every branch and hit the catch-all 500 ``Quit that! You don't
have rights to view this.``

- ``/user/update`` (the original report): toggling enable/disable from
  组织与成员 → MemberTable.
- ``/user/list``: ``FilterByUser``、``ColFilterUser``、``SubjectSearchUser``
  fallback、``DepartmentUsersSelect`` 等组件统统依赖它；子租户管理员触达
  其中任意一个就 500（"举一反三" 同根坑）。

``bisheng.user.api.user`` is a heavy module the lean test venv cannot import
(see ``test_logout_scope_clear.py`` for the same workaround). We pin the
fix at the AST level: the new helpers exist and the endpoints route through
the new scope helpers. End-to-end behaviour is covered by ops handbook QA.
"""

from __future__ import annotations

import ast
from pathlib import Path


USER_PY = (
    Path(__file__).resolve().parent.parent
    / 'bisheng' / 'user' / 'api' / 'user.py'
)


def _function_source(name: str) -> str:
    src = USER_PY.read_text(encoding='utf-8')
    tree = ast.parse(src)
    for node in tree.body:
        if (
            isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name == name
        ):
            seg = ast.get_source_segment(src, node)
            if seg:
                return seg
    return ''


def test_tenant_admin_helper_defined():
    """新 helper 必须存在并带 docstring，避免后续 squash/合并误删。"""
    src = _function_source('_tenant_admin_can_manage_member_account_status')
    assert src, '_tenant_admin_can_manage_member_account_status missing'
    # docstring + tenant-admin FGA check + path prefix scope check
    assert '子租户管理员' in src or 'tenant#admin' in src or 'tenant admin' in src.lower()
    assert "object_type='tenant'" in src or 'object_type="tenant"' in src
    assert 'startswith(mount_path)' in src or 'mount_path' in src
    assert 'ROOT_TENANT_ID' in src, 'Root tenant must be short-circuited'


def test_unified_gate_combines_dept_and_tenant_branches():
    src = _function_source('_can_manage_member_account_status')
    assert src, '_can_manage_member_account_status missing'
    assert '_dept_admin_can_manage_member_account_status' in src
    assert '_tenant_admin_can_manage_member_account_status' in src


def test_update_endpoint_calls_unified_gate_not_dept_only():
    """``/user/update`` 必须走统一闸门，不能再硬卡 dept-admin 单一分支。"""
    src = _function_source('update')
    assert src, 'update endpoint missing'
    # New gate is wired in.
    assert '_can_manage_member_account_status(' in src, (
        'update() must call the unified gate so tenant admins are admitted'
    )
    # Old, dept-only gate must no longer be the gating call.
    assert (
        '_dept_admin_can_manage_member_account_status(' not in src
    ), (
        'update() should delegate to the unified gate; '
        'direct dept-admin call is the bug being fixed'
    )


# ---------------------------------------------------------------------------
# /user/list: tenant-admin scope (举一反三)
# ---------------------------------------------------------------------------

def test_tenant_admin_scoped_user_ids_helper_defined():
    """子租户管理员可见用户 helper 必须存在并复用 path 子树查询。"""
    src = _function_source('_tenant_admin_scoped_user_ids')
    assert src, '_tenant_admin_scoped_user_ids missing'
    assert "object_type='tenant'" in src or 'object_type="tenant"' in src
    assert 'aget_subtree_ids' in src, 'tenant scope must walk mount-subtree path'
    assert 'ROOT_TENANT_ID' in src, 'Root tenant must be short-circuited'
    assert 'UserDepartment' in src, (
        'tenant scope must reverse-lookup user_ids via UserDepartment'
    )


def test_list_user_combines_dept_and_tenant_scope():
    """``/user/list`` 必须把 dept-admin 与 tenant-admin 范围合并，单分支不再够用。"""
    src = _function_source('list_user')
    assert src, 'list_user endpoint missing'
    # New helper must be invoked alongside the dept-admin one.
    assert '_tenant_admin_scoped_user_ids(' in src, (
        'list_user must derive tenant-admin scope so Child Admins see their tenant users'
    )
    assert '_department_admin_scoped_user_ids(' in src, (
        'list_user must keep dept-admin scope as well'
    )
    # The reject branch must now key off the *combined* scope being absent,
    # not just dept_scoped_ids being None (the old, broken check).
    assert 'org_scoped_ids' in src or 'tenant_scoped_ids' in src, (
        'list_user must combine dept+tenant scope before deciding to 500'
    )
    # Sanity: the buggy single-source guard ``if dept_scoped_ids is None: raise``
    # must not be the gating condition any more.
    assert 'if dept_scoped_ids is None:\n' not in src, (
        'old dept-only guard must be replaced by the combined-scope guard'
    )
