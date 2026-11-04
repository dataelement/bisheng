"""F003 T004: identity → audit department scope (design decision 4)."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

for _mod in ("celery", "celery.schedules", "celery.app", "celery.app.task"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.org_snapshot import AuditDeptScope
from bisheng.department.domain.services import audit_dept_scope as module
from bisheng.department.domain.services.audit_dept_scope import AuditDeptScopeService


def _user(*, global_super=False, admin=False):
    return SimpleNamespace(user_id=7, is_global_super=global_super, is_admin=lambda: admin)


def _dept(dept_id, path, tenant_id=1, is_deleted=0):
    return SimpleNamespace(id=dept_id, path=path, tenant_id=tenant_id, is_deleted=is_deleted)


@pytest.fixture()
def identity(monkeypatch):
    state = SimpleNamespace(tenant_admin=False, admin_departments=[], menu=True, primary=None)

    async def _tenant_admin(user_id, tenant_id):
        return state.tenant_admin

    async def _admin_departments(user_id):
        return state.admin_departments

    async def _menu(cls, login_user, *, is_department_admin):
        return state.menu

    async def _primary(user_id):
        return SimpleNamespace(department_id=state.primary) if state.primary else None

    monkeypatch.setattr("bisheng.common.permission_identity.check_tenant_admin", _tenant_admin)
    monkeypatch.setattr(module.DepartmentDao, "aget_user_admin_departments", _admin_departments)
    monkeypatch.setattr(AuditDeptScopeService, "_has_audit_menu", classmethod(_menu))
    monkeypatch.setattr(module.UserDepartmentDao, "aget_user_primary_department", _primary)
    return state


async def test_global_super_is_unrestricted(identity):
    identity.admin_departments = [_dept(2, "/1/2/")]
    assert await AuditDeptScopeService.resolve(_user(global_super=True), None) == AuditDeptScope.unlimited()


async def test_tenant_admin_who_also_manages_a_department_is_unrestricted(identity):
    identity.tenant_admin = True
    identity.admin_departments = [_dept(2, "/1/2/")]
    assert await AuditDeptScopeService.resolve(_user(), 1) == AuditDeptScope.unlimited()


async def test_department_admin_gets_union_of_paths_in_audit_tenant(identity):
    identity.admin_departments = [
        _dept(2, "/1/2/"),
        _dept(9, "/1/9/"),
        _dept(30, "/30/", tenant_id=5),
        _dept(11, "/1/11/", is_deleted=1),
    ]
    scope = await AuditDeptScopeService.resolve(_user(), 1)
    assert scope == AuditDeptScope.restricted(admin_paths=["/1/2/", "/1/9/"])


async def test_menu_role_sees_only_primary_department(identity):
    identity.primary = 3
    assert await AuditDeptScopeService.resolve(_user(), 1) == AuditDeptScope.restricted(exact_ids=[3])


async def test_menu_role_without_primary_department_sees_nothing(identity):
    scope = await AuditDeptScopeService.resolve(_user(), 1)
    assert scope == AuditDeptScope.restricted()
    assert not scope.unrestricted and not scope.admin_paths and not scope.exact_ids


async def test_department_admin_outside_audit_tenant_falls_back_to_primary(identity):
    identity.admin_departments = [_dept(30, "/30/", tenant_id=5)]
    identity.primary = 3
    assert await AuditDeptScopeService.resolve(_user(), 1) == AuditDeptScope.restricted(exact_ids=[3])


async def test_without_audit_menu_is_rejected(identity):
    identity.menu = False
    identity.admin_departments = [_dept(2, "/1/2/")]
    with pytest.raises(UnAuthorizedError):
        await AuditDeptScopeService.resolve(_user(), 1)


async def test_group_admin_without_menu_is_rejected(identity, monkeypatch):
    identity.menu = False
    monkeypatch.setattr(
        "bisheng.database.models.user_group.UserGroupDao.aget_user_admin_group",
        AsyncMock(return_value=[SimpleNamespace(group_id=4)]),
    )
    with pytest.raises(UnAuthorizedError):
        await AuditDeptScopeService.resolve(_user(), 1)
