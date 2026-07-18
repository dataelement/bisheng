"""F038 T002: unified user-scope helper for lazy department tree.

`_aget_user_scope(login_user)` extracts the three-tier visibility scope that
`aget_tree` computes inline, so the new lazy children/search/path-tree endpoints
reuse the EXACT same scope and can't drift. Returns ``(is_sys_admin, admin_paths)``:
- system admin  → ``(True, set())``  (full tree; no admin_paths needed)
- dept admin    → ``(False, {<admin dept paths>})``
- tenant admin  → ``(False, {<mount path>, ...})``  (union with dept-admin paths)
- neither, no admin depts → raises ``DepartmentPermissionDeniedError``

These are unit tests: the underlying admin/tenant lookups are mocked, so no DB.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.department import DepartmentPermissionDeniedError

_MOD = "bisheng.department.domain.services.department_service"


def _login_user(user_id=7, tenant_id=1):
    return SimpleNamespace(user_id=user_id, tenant_id=tenant_id, user_role=[])


async def _call_scope(login_user):
    from bisheng.department.domain.services.department_service import _aget_user_scope

    return await _aget_user_scope(login_user)


class TestAgetUserScope:
    async def test_system_admin_full_scope(self):
        login_user = _login_user()
        with patch(f"{_MOD}._is_admin", return_value=True):
            is_sys_admin, admin_paths = await _call_scope(login_user)
        assert is_sys_admin is True
        assert admin_paths == set()

    async def test_dept_admin_paths(self):
        from bisheng.database.models.department import DepartmentDao

        login_user = _login_user()
        admin_depts = [
            SimpleNamespace(id=21, path="/1/21/"),
            SimpleNamespace(id=30, path="/1/30/"),
        ]
        with (
            patch(f"{_MOD}._is_admin", return_value=False),
            patch.object(
                DepartmentDao, "aget_user_admin_departments", new_callable=AsyncMock, return_value=admin_depts
            ),
            patch(f"{_MOD}._is_tenant_admin", new_callable=AsyncMock, return_value=False),
        ):
            is_sys_admin, admin_paths = await _call_scope(login_user)
        assert is_sys_admin is False
        assert admin_paths == {"/1/21/", "/1/30/"}

    async def test_tenant_admin_mount_path(self):
        from bisheng.database.models.department import DepartmentDao

        login_user = _login_user()
        with (
            patch(f"{_MOD}._is_admin", return_value=False),
            patch.object(DepartmentDao, "aget_user_admin_departments", new_callable=AsyncMock, return_value=[]),
            patch(f"{_MOD}._is_tenant_admin", new_callable=AsyncMock, return_value=True),
            patch(f"{_MOD}._aget_user_tenant_root_path", new_callable=AsyncMock, return_value="/5/"),
        ):
            is_sys_admin, admin_paths = await _call_scope(login_user)
        assert is_sys_admin is False
        assert admin_paths == {"/5/"}

    async def test_dept_and_tenant_admin_union(self):
        from bisheng.database.models.department import DepartmentDao

        login_user = _login_user()
        admin_depts = [SimpleNamespace(id=21, path="/1/21/")]
        with (
            patch(f"{_MOD}._is_admin", return_value=False),
            patch.object(
                DepartmentDao, "aget_user_admin_departments", new_callable=AsyncMock, return_value=admin_depts
            ),
            patch(f"{_MOD}._is_tenant_admin", new_callable=AsyncMock, return_value=True),
            patch(f"{_MOD}._aget_user_tenant_root_path", new_callable=AsyncMock, return_value="/5/"),
        ):
            is_sys_admin, admin_paths = await _call_scope(login_user)
        assert is_sys_admin is False
        assert admin_paths == {"/1/21/", "/5/"}

    async def test_non_admin_denied(self):
        from bisheng.database.models.department import DepartmentDao

        login_user = _login_user()
        with (
            patch(f"{_MOD}._is_admin", return_value=False),
            patch.object(DepartmentDao, "aget_user_admin_departments", new_callable=AsyncMock, return_value=[]),
            patch(f"{_MOD}._is_tenant_admin", new_callable=AsyncMock, return_value=False),
        ):
            with pytest.raises(DepartmentPermissionDeniedError):
                await _call_scope(login_user)
