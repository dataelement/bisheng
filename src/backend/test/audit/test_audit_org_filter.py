"""F003 T005: system-operation audit — department scope and organisation filter.

Runs the real service + DAO against the audit SQLite engine with a department
table beside it, so the closure and descendant subqueries execute for real.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import text

from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.org_snapshot import DEPT_NONE, DEPT_NOT_APPLICABLE, DeptSelection
from test.audit.conftest import insert_audit, make_user_payload
from test.fixtures.table_definitions import TABLE_DEFINITIONS

TENANT = 2
# (id, name, path, status)
_DEPTS = [
    (1, "Root", "/1/", "active"),
    (2, "Sales", "/1/2/", "active"),
    (3, "East", "/1/2/3/", "active"),
    (4, "OldTeam", "/1/2/4/", "archived"),
    (20, "R&D", "/1/20/", "active"),
]


@pytest.fixture()
def org(audit_engine, audit_session, patch_audit_dao, audit_lookups):
    with audit_engine.begin() as conn:
        conn.execute(text(TABLE_DEFINITIONS["department"]))
        conn.execute(text("DELETE FROM department"))
        conn.execute(text("DELETE FROM auditlog"))
        for dept_id, name, path, status in _DEPTS:
            conn.execute(
                text(
                    "INSERT INTO department (id, dept_id, name, path, status, tenant_id) "
                    "VALUES (:id, :code, :name, :path, :status, :tenant)"
                ),
                {
                    "id": dept_id,
                    "code": f"BS@{dept_id}",
                    "name": name,
                    "path": path,
                    "status": status,
                    "tenant": TENANT,
                },
            )
    for operator_id, dept_id in [
        (31, 2),
        (32, 3),
        (33, 4),
        (34, 20),
        (35, DEPT_NONE),
        (0, DEPT_NOT_APPLICABLE),
        (36, None),
    ]:
        insert_audit(
            audit_session,
            action="app.publish",
            operator_id=operator_id,
            operator_name=f"u{operator_id}",
            tenant_id=TENANT,
            operator_dept_id=dept_id,
        )
    return audit_session


def _user(admin=False):
    return make_user_payload(user_id=900, is_admin=admin, is_global_super=False)


def _scope_patches():
    return (
        patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
        patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=TENANT),
        patch("bisheng.department.domain.services.audit_dept_scope.get_current_tenant_id", return_value=TENANT),
    )


async def _operators(user, *, selection=None, group_ids=None):
    p1, p2, p3 = _scope_patches()
    with p1, p2, p3:
        resp = await AuditLogService.get_audit_log(
            user, group_ids or [], [], None, None, None, None, 1, 50, dept_selection=selection
        )
    if not isinstance(resp, dict):
        return resp
    return sorted(row["operator_id"] for row in resp["data"]["data"])


async def _export_operators(user, *, selection=None):
    p1, p2, p3 = _scope_patches()
    with p1, p2, p3:
        rows, total = await AuditLogService.export_audit_log(
            user, [], [], None, None, None, None, dept_selection=selection
        )
    assert total == len(rows)
    return sorted(row["operator_id"] for row in rows)


def _dept_admin(audit_identity, *paths):
    audit_identity.menu = True
    audit_identity.admin_departments = [SimpleNamespace(path=p, tenant_id=TENANT, is_deleted=0) for p in paths]


class TestUnrestricted:
    async def test_no_selection_lists_everything(self, org):
        assert await _operators(_user(admin=True)) == [0, 31, 32, 33, 34, 35, 36]

    async def test_selection_with_descendants_and_fixed_items(self, org):
        selection = DeptSelection.of([2], include_none=True, include_unrecorded=True)
        assert await _operators(_user(admin=True), selection=selection) == [31, 32, 35, 36]

    async def test_selection_without_descendants(self, org):
        selection = DeptSelection.of([2], include_descendants=False)
        assert await _operators(_user(admin=True), selection=selection) == [31]


class TestTenantAdmin:
    @pytest.fixture()
    def tenant_admin(self, monkeypatch):
        async def _tenant_admin(user_id, tenant_id):
            return tenant_id == TENANT

        async def _roots(tenant_scope):
            assert tenant_scope == TENANT
            return ["/1/"]

        monkeypatch.setattr("bisheng.common.permission_identity.check_tenant_admin", _tenant_admin)
        monkeypatch.setattr(
            "bisheng.department.domain.services.audit_dept_scope.AuditDeptRepository.root_paths",
            _roots,
        )

    async def test_rbac_admin_reads_none_and_not_applicable_but_not_unrecorded(self, org, tenant_admin):
        assert await _operators(_user(admin=True)) == [0, 31, 32, 33, 34, 35]
        assert await _export_operators(_user(admin=True)) == [0, 31, 32, 33, 34, 35]

    async def test_none_option_applies_and_unrecorded_option_is_ignored(self, org, tenant_admin):
        assert await _operators(_user(admin=True), selection=DeptSelection.of(include_none=True)) == [35]
        selection = DeptSelection.of([3], include_none=True, include_unrecorded=True)
        assert await _operators(_user(admin=True), selection=selection) == [32, 35]


class TestDepartmentAdmin:
    async def test_closure_includes_archived_and_excludes_sentinels(self, org, audit_identity):
        _dept_admin(audit_identity, "/1/2/")
        assert await _operators(_user()) == [31, 32, 33]

    async def test_fixed_items_dropped_and_intersected(self, org, audit_identity):
        _dept_admin(audit_identity, "/1/2/")
        selection = DeptSelection.of([3], include_none=True, include_unrecorded=True)
        assert await _operators(_user(), selection=selection) == [32]

    async def test_tampered_out_of_scope_selection_is_empty(self, org, audit_identity):
        _dept_admin(audit_identity, "/1/2/")
        assert await _operators(_user(), selection=DeptSelection.of([20])) == []

    async def test_export_matches_the_list(self, org, audit_identity):
        _dept_admin(audit_identity, "/1/2/")
        selection = DeptSelection.of([2])
        assert await _export_operators(_user(), selection=selection) == await _operators(_user(), selection=selection)

    async def test_group_filter_only_narrows(self, org, audit_identity, audit_lookups):
        _dept_admin(audit_identity, "/1/2/")
        audit_lookups.group_users = [SimpleNamespace(group_id=5, user_id=32), SimpleNamespace(group_id=5, user_id=34)]
        # Group 5 holds 32 (inside the closure) and 34 (outside): the group never widens the scope.
        assert await _operators(_user(), group_ids=["5"]) == [32]


class TestMenuRole:
    async def test_primary_department_only_even_with_descendants(self, org, audit_identity):
        audit_identity.menu = True
        audit_identity.primary_dept_id = 2
        assert await _operators(_user(), selection=DeptSelection.of([2])) == [31]

    async def test_without_menu_is_refused(self, org):
        resp = await _operators(_user())
        assert resp.status_code == UnAuthorizedError.Code


class TestOperatorCandidates:
    async def test_limited_to_the_scope(self, org, audit_identity):
        _dept_admin(audit_identity, "/1/2/")
        p1, p2, p3 = _scope_patches()
        with p1, p2, p3:
            operators = await AuditLogService.get_all_operators(_user())
        assert sorted(one["user_id"] for one in operators) == [31, 32, 33]

    async def test_refused_without_menu(self, org):
        p1, p2, p3 = _scope_patches()
        with p1, p2, p3, pytest.raises(UnAuthorizedError):
            await AuditLogService.get_all_operators(_user())
