"""F003 T002: organisation snapshot resolution and the department predicate.

Runs the real department DAOs against one SQLite file shared by a sync and an
aiosqlite engine, so both resolve paths and the predicate SQL are exercised.
"""

import sys
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, insert, select, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

for _mod in ("celery", "celery.schedules", "celery.app", "celery.app.task"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from bisheng.database.models import org_snapshot
from bisheng.database.models.org_snapshot import (
    DEPT_NONE,
    DEPT_NOT_APPLICABLE,
    AuditDeptScope,
    DeptSelection,
    astamp_audit_logs,
    build_dept_predicate,
    resolve_user_dept,
    session_subject,
    stamp,
    stamp_audit_logs,
)
from test.fixtures.table_definitions import create_tables

# (id, name, parent_id, path, status)
_DEPTS = [
    (1, "Root", None, "/1/", "active"),
    (2, "Sales", 1, "/1/2/", "active"),
    (3, "East", 2, "/1/2/3/", "active"),
    (4, "OldTeam", 2, "/1/2/4/", "archived"),
    (20, "R&D", 1, "/1/20/", "active"),
]
# (user_id, department_id, is_primary)
_MEMBERS = [(10, 3, 1), (10, 20, 0), (11, 20, 0), (12, 4, 1)]

_metadata = MetaData()
_rows = Table("rows", _metadata, Column("id", Integer, primary_key=True), Column("operator_dept_id", Integer))
# row id → operator_dept_id
_ROWS = {1: 1, 2: 2, 3: 3, 4: 4, 5: 20, 6: DEPT_NONE, 7: DEPT_NOT_APPLICABLE, 8: None}


@pytest.fixture()
def engines(tmp_path):
    db = tmp_path / "org.db"
    sync_engine = create_engine(f"sqlite:///{db}")
    create_tables(sync_engine, "department", "user_department")
    _metadata.create_all(sync_engine)
    with sync_engine.begin() as conn:
        for dept_id, name, parent_id, path, status in _DEPTS:
            conn.execute(
                text(
                    "INSERT INTO department (id, dept_id, name, parent_id, path, status) "
                    "VALUES (:id, :code, :name, :parent_id, :path, :status)"
                ),
                {
                    "id": dept_id,
                    "code": f"BS@{dept_id}",
                    "name": name,
                    "parent_id": parent_id,
                    "path": path,
                    "status": status,
                },
            )
        for user_id, department_id, is_primary in _MEMBERS:
            conn.execute(
                text(
                    "INSERT INTO user_department (user_id, department_id, is_primary) "
                    "VALUES (:user_id, :department_id, :is_primary)"
                ),
                {"user_id": user_id, "department_id": department_id, "is_primary": is_primary},
            )
        conn.execute(insert(_rows), [{"id": k, "operator_dept_id": v} for k, v in _ROWS.items()])
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db}")

    @contextmanager
    def _sync_factory():
        with Session(sync_engine) as session:
            yield session

    @asynccontextmanager
    async def _async_factory():
        async with AsyncSession(async_engine) as session:
            yield session

    with (
        patch("bisheng.database.models.department.get_sync_db_session", _sync_factory),
        patch("bisheng.database.models.department.get_async_db_session", _async_factory),
    ):
        yield sync_engine
    sync_engine.dispose()


def _matching(engine, scope, selection=None) -> set[int]:
    predicate = build_dept_predicate(_rows.c.operator_dept_id, scope, selection)
    statement = select(_rows.c.id)
    if predicate is not None:
        statement = statement.where(predicate)
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(statement)}


class TestResolve:
    def test_primary_department_with_name_path(self, engines):
        assert resolve_user_dept(10) == (3, "Root/Sales/East")

    def test_no_primary_membership_is_none_sentinel(self, engines):
        assert resolve_user_dept(11) == (DEPT_NONE, None)
        assert resolve_user_dept(999) == (DEPT_NONE, None)

    def test_archived_primary_department_still_recorded(self, engines):
        assert resolve_user_dept(12) == (4, "Root/Sales/OldTeam")

    def test_lookup_failure_leaves_unrecorded(self, engines):
        with patch.object(org_snapshot.UserDepartmentDao, "get_user_primary_department", side_effect=RuntimeError):
            assert resolve_user_dept(10) == (None, None)

    async def test_batch_matches_single(self, engines):
        result = await org_snapshot.aresolve_users_dept([10, 11, 12, None, 10])
        assert result == {10: (3, "Root/Sales/East"), 11: (DEPT_NONE, None), 12: (4, "Root/Sales/OldTeam")}

    async def test_batch_failure_leaves_unrecorded(self, engines):
        with patch.object(org_snapshot.UserDepartmentDao, "aget_by_user_ids", side_effect=RuntimeError):
            assert await org_snapshot.aresolve_users_dept([10]) == {10: (None, None)}


def _audit_row(operator_id, dept_id=None, dept_path=None):
    return SimpleNamespace(operator_id=operator_id, operator_dept_id=dept_id, operator_dept_path=dept_path)


class TestStamp:
    def test_system_operator_is_not_applicable(self, engines):
        rows = [_audit_row(0), _audit_row(10)]
        stamp_audit_logs(rows)
        assert [(r.operator_dept_id, r.operator_dept_path) for r in rows] == [
            (DEPT_NOT_APPLICABLE, None),
            (3, "Root/Sales/East"),
        ]

    def test_already_stamped_row_is_kept(self, engines):
        row = _audit_row(10, dept_id=20, dept_path="Root/R&D")
        stamp_audit_logs([row])
        assert (row.operator_dept_id, row.operator_dept_path) == (20, "Root/R&D")

    async def test_async_batch(self, engines):
        rows = [_audit_row(0), _audit_row(10), _audit_row(11)]
        await astamp_audit_logs(rows)
        assert [r.operator_dept_id for r in rows] == [DEPT_NOT_APPLICABLE, 3, DEPT_NONE]

    def test_open_api_session_is_not_applicable(self, engines):
        row = SimpleNamespace(user_id=10, api_subject_type="app_secret", operator_dept_id=None, operator_dept_path=None)
        stamp([row], session_subject)
        assert row.operator_dept_id == DEPT_NOT_APPLICABLE


class TestPredicate:
    def test_unrestricted_without_selection_has_no_condition(self, engines):
        assert build_dept_predicate(_rows.c.operator_dept_id, AuditDeptScope.unlimited()) is None

    def test_descendants_follow_active_tree_and_not_prefix_siblings(self, engines):
        # /1/2/ must not match /1/20/; archived 4 is not pulled in as a descendant.
        assert _matching(engines, AuditDeptScope.unlimited(), DeptSelection.of([2])) == {2, 3}

    def test_selected_archived_department_matches_itself(self, engines):
        assert _matching(engines, AuditDeptScope.unlimited(), DeptSelection.of([4])) == {4}

    def test_exact_selection_without_descendants(self, engines):
        assert _matching(engines, AuditDeptScope.unlimited(), DeptSelection.of([2], include_descendants=False)) == {2}

    def test_unattributed_options(self, engines):
        selection = DeptSelection.of(include_none=True, include_unrecorded=True)
        assert _matching(engines, AuditDeptScope.unlimited(), selection) == {6, 8}

    def test_admin_closure_includes_archived_and_excludes_sentinels(self, engines):
        scope = AuditDeptScope.restricted(admin_paths=["/1/2/"])
        assert _matching(engines, scope) == {2, 3, 4}

    def test_restricted_drops_unattributed_options(self, engines):
        scope = AuditDeptScope.restricted(admin_paths=["/1/2/"])
        selection = DeptSelection.of([3], include_none=True, include_unrecorded=True)
        assert _matching(engines, scope, selection) == {3}

    def test_selection_outside_closure_matches_nothing(self, engines):
        scope = AuditDeptScope.restricted(admin_paths=["/1/2/"])
        assert _matching(engines, scope, DeptSelection.of([20])) == set()

    def test_exact_primary_department_only(self, engines):
        assert _matching(engines, AuditDeptScope.restricted(exact_ids=[2])) == {2}

    def test_empty_closure_matches_nothing(self, engines):
        assert _matching(engines, AuditDeptScope.restricted()) == set()
