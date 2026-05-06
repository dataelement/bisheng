"""Tests for member-edit-form scope filtering.

Regression: a sub-tenant admin opening "组织与成员 → 编辑人员" hit 21009
"没有该部门操作权限" when the target user had affiliate rows in departments
outside the operator's admin scope. The old logic loaded the target user's
full dept set and called the throwing ``_check_permission`` for each, so a
single foreign affiliate failed the entire request.

Fix: filter the target's dept list with the non-throwing ``_can_access_dept``
in both ``aget_member_edit_form`` and ``aapply_member_edit`` so foreign
affiliates are silently dropped from the dialog and the save payload.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.department import DepartmentPermissionDeniedError
from bisheng.department.domain.services import department_service as m


def _user(user_id=10, user_role=None, tenant_id=5):
    return SimpleNamespace(
        user_id=user_id,
        user_role=user_role if user_role is not None else [2],
        tenant_id=tenant_id,
    )


@pytest.mark.asyncio
async def test_can_access_dept_returns_true_when_check_passes():
    with patch.object(
        m, '_check_permission', new_callable=AsyncMock, return_value=None,
    ):
        assert await m._can_access_dept(_user(), 1) is True


@pytest.mark.asyncio
async def test_can_access_dept_returns_false_on_permission_denied():
    with patch.object(
        m, '_check_permission', new_callable=AsyncMock,
        side_effect=DepartmentPermissionDeniedError(),
    ):
        assert await m._can_access_dept(_user(), 1) is False


@pytest.mark.asyncio
async def test_aget_assignable_roles_catalog_returns_empty_when_all_inaccessible():
    """If every dept is out of scope, return {} instead of raising 21009.

    Pre-fix this raised on the first inaccessible dept, breaking the whole
    edit-form load when a sub-tenant admin opened a member with foreign
    affiliate rows.
    """
    out_a = SimpleNamespace(id=20, dept_id='BS@a', path='/1/20/')
    out_b = SimpleNamespace(id=21, dept_id='BS@b', path='/1/21/')

    with patch.object(
        m, '_can_access_dept', new_callable=AsyncMock, return_value=False,
    ):
        catalog = await m.DepartmentService._aget_assignable_roles_catalog(
            [out_a, out_b], _user(),
        )

    assert catalog == {}


@pytest.mark.asyncio
async def test_aget_member_edit_form_drops_foreign_affiliate_dept():
    """End-to-end: a sub-tenant admin opens the edit dialog for a member who
    has an affiliate row in a foreign subtree. Pre-fix this raised 21009;
    post-fix the foreign affiliate row is silently filtered out.
    """
    from bisheng.database.models.department import DepartmentDao, UserDepartmentDao

    ctx_dept = SimpleNamespace(
        id=10, dept_id='BS@ctx', name='本部门', status='active', path='/1/10/',
    )
    foreign_dept = SimpleNamespace(
        id=20, dept_id='BS@foreign', name='跨域兼职', status='active', path='/1/20/',
    )
    target_user = SimpleNamespace(
        user_id=99, user_name='赵亚运', external_id='BS@u', source='local', delete=0,
    )
    primary_ud = SimpleNamespace(id=1, user_id=99, department_id=10, is_primary=1)
    foreign_ud = SimpleNamespace(id=2, user_id=99, department_id=20, is_primary=0)

    operator = _user(user_id=10, tenant_id=5)

    from contextlib import asynccontextmanager

    class _MemResult:
        def first(self):
            return primary_ud

    class _DeptResult:
        def first(self):
            return ctx_dept

    class _FakeSession:
        def __init__(self):
            self._exec_calls = 0

        async def exec(self, _stmt):
            self._exec_calls += 1
            # First exec is for ctx_dept lookup; second is for membership lookup.
            return _DeptResult() if self._exec_calls == 1 else _MemResult()

    @asynccontextmanager
    async def _session_cm():
        yield _FakeSession()

    async def fake_can_access(_login_user, dept_id):
        # Operator scope only covers ctx_dept; foreign affiliate is denied.
        return int(dept_id) == 10

    # Stub the catalog/groups so we only assert the dept-filtering side-effect.
    async def fake_catalog(cls, depts, _login_user):
        return {d.dept_id: [] for d in depts}

    async def fake_groups(cls, _login_user):
        return []

    with patch(
        'bisheng.department.domain.services.department_service.get_async_db_session',
        side_effect=_session_cm,
    ), patch.object(
        m, '_can_access_dept',
        new_callable=AsyncMock, side_effect=fake_can_access,
    ), patch.object(
        m, '_check_permission', new_callable=AsyncMock, return_value=None,
    ), patch.object(
        UserDepartmentDao, 'aget_user_departments',
        new_callable=AsyncMock, return_value=[primary_ud, foreign_ud],
    ), patch.object(
        DepartmentDao, 'aget_by_ids',
        new_callable=AsyncMock, return_value=[ctx_dept, foreign_dept],
    ), patch(
        'bisheng.user.domain.models.user.UserDao.aget_user',
        new_callable=AsyncMock, return_value=target_user,
    ), patch(
        'bisheng.user.domain.models.user_role.UserRoleDao.aget_user_roles',
        new_callable=AsyncMock, return_value=[],
    ), patch(
        'bisheng.database.models.user_group.UserGroupDao.aget_user_group',
        new_callable=AsyncMock, return_value=[],
    ), patch.object(
        m.DepartmentService, '_aget_assignable_roles_catalog',
        new=classmethod(fake_catalog),
    ), patch.object(
        m.DepartmentService, '_manageable_group_options',
        new=classmethod(fake_groups),
    ):
        result = await m.DepartmentService.aget_member_edit_form(
            'BS@ctx', 99, operator,
        )

    # Catalog must only include the in-scope dept, not the foreign affiliate.
    assert 'BS@ctx' in result['assignable_roles_catalog']
    assert 'BS@foreign' not in result['assignable_roles_catalog']
    # No affiliate row should surface for a dept the operator can't manage.
    affiliate_dept_ids = [row['dept_id'] for row in result['affiliate_rows']]
    assert 'BS@foreign' not in affiliate_dept_ids
    # Primary block remains valid (ctx_dept is the target's primary).
    assert result['primary_department']['dept_id'] == 'BS@ctx'
