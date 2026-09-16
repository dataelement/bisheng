"""F056 T022 / T026 — the audit query's "object application" filter.

Covers (spec AC-21, AC-28, AC-31; design pit 15):

* DAO predicate: rows with ``target_type='app'`` **and** rows carrying
  ``metadata.app_id`` (the F055 ``app.release.*`` shape) both match; other
  apps' rows and unrelated rows do not; the count agrees with the page.
* A deleted application's rows are still matched and the name snapshot
  (``object_name``) is what the response carries.
* Service boundary: a tenant admin naming another tenant's application is
  rejected, never silently narrowed; a global super is not.
* Pit 15: with a group filter in force, structured v2 rows (``group_ids``
  NULL) written by a member of that group are still returned.
"""

from unittest.mock import patch

import pytest

from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.audit_log import AuditLogDao
from test.audit.conftest import insert_audit, make_app, make_user_payload

APP_A = "app-aaaa"
APP_B = "app-bbbb"


def _seed_two_apps(session):
    insert_audit(session, action="app.publish", target_type="app", target_id=APP_A, object_name="Alpha")
    insert_audit(
        session,
        action="app.release.submit",
        target_type="app_version",
        target_id="ver-a-1",
        audit_metadata={"app_id": APP_A, "deployment_id": "dep-1", "version_no": 1},
    )
    insert_audit(session, action="app.stop", target_type="app", target_id=APP_B, object_name="Beta")
    insert_audit(
        session,
        action="app.release.online",
        target_type="app_version",
        target_id="ver-b-3",
        audit_metadata={"app_id": APP_B, "version_no": 3},
    )
    insert_audit(session, action="tenant.mount", target_type="tenant", target_id="9")
    # A metadata blob that merely *mentions* the id in another field must not match.
    insert_audit(session, action="llm.server.create", audit_metadata={"note": APP_A, "app_id": "other"})


class TestObjectAppPredicate:
    async def test_matches_state_and_release_rows_for_one_app(self, patch_audit_dao, audit_session):
        _seed_two_apps(audit_session)

        rows, total = await AuditLogDao.get_audit_logs([], target_app_id=APP_A, page=1, limit=20)

        assert total == 2
        assert {r.action for r in rows} == {"app.publish", "app.release.submit"}

    async def test_other_app_and_unrelated_rows_excluded(self, patch_audit_dao, audit_session):
        _seed_two_apps(audit_session)

        rows, total = await AuditLogDao.get_audit_logs([], target_app_id=APP_B)

        assert total == 2
        assert {r.target_id for r in rows} == {APP_B, "ver-b-3"}

    async def test_unknown_app_matches_nothing(self, patch_audit_dao, audit_session):
        _seed_two_apps(audit_session)

        rows, total = await AuditLogDao.get_audit_logs([], target_app_id="nope")

        assert (rows, total) == ([], 0)

    async def test_ands_with_tenant_scope(self, patch_audit_dao, audit_session):
        insert_audit(session=audit_session, action="app.publish", target_type="app", target_id=APP_A, tenant_id=2)
        insert_audit(
            session=audit_session,
            action="app.delete",
            target_type="app",
            target_id=APP_A,
            tenant_id=3,
            operator_tenant_id=3,
        )

        rows, total = await AuditLogDao.get_audit_logs([], target_app_id=APP_A, tenant_scope=2)

        assert total == 1
        assert rows[0].action == "app.publish"

    async def test_pages_are_ordered_newest_first_with_id_tiebreak(self, patch_audit_dao, audit_session):
        # Same-second inserts: the id tiebreaker must keep the two pages disjoint.
        for i in range(5):
            insert_audit(audit_session, action="app.meta_update", target_type="app", target_id=APP_A, note=str(i))
        page1, total = await AuditLogDao.get_audit_logs([], target_app_id=APP_A, page=1, limit=3)
        page2, _ = await AuditLogDao.get_audit_logs([], target_app_id=APP_A, page=2, limit=3)
        assert total == 5
        assert len(page1) == 3 and len(page2) == 2
        assert {r.id for r in page1}.isdisjoint({r.id for r in page2})


class TestObjectAppPredicateDialects:
    """The SQLite runs above exercise the LIKE fallback only; pin what the
    MySQL branch compiles to so the JSON-native path cannot silently rot."""

    def test_mysql_branch_uses_json_extract(self):
        from sqlalchemy.dialects import mysql

        from bisheng.core.database.dialect_helpers import json_object_field_equals
        from bisheng.database.models.audit_log import AuditLog

        expr = json_object_field_equals(AuditLog.audit_metadata, "app_id", APP_A, "mysql")
        sql = str(expr.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
        assert "json_unquote(json_extract(auditlog.metadata, '$.app_id'))" in sql
        assert sql.endswith(f"= '{APP_A}'")

    def test_dm_branch_matches_the_quoted_pair_only(self):
        from sqlalchemy.dialects import sqlite

        from bisheng.core.database.dialect_helpers import json_object_field_equals
        from bisheng.database.models.audit_log import AuditLog

        expr = json_object_field_equals(AuditLog.audit_metadata, "app_id", APP_A, "dm")
        sql = str(expr.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        assert sql.endswith(f"""LIKE '%"app_id": "{APP_A}"%'""")


class TestGroupMemberFallback:
    """Design pit 15: v2 rows never carry ``group_ids``."""

    async def test_v2_rows_by_group_member_match_group_filter(self, patch_audit_dao, audit_session):
        insert_audit(audit_session, action="app.publish", operator_id=42, group_ids=None)
        insert_audit(audit_session, action="app.stop", operator_id=99, group_ids=None)
        insert_audit(audit_session, system_id="build", event_type="create_build", operator_id=7, group_ids=[5])

        rows, total = await AuditLogDao.get_audit_logs(["5"], group_member_ids=[42])

        assert total == 2
        assert {r.operator_id for r in rows} == {42, 7}

    async def test_without_member_ids_behaviour_is_unchanged(self, patch_audit_dao, audit_session):
        insert_audit(audit_session, action="app.publish", operator_id=42, group_ids=None)
        insert_audit(audit_session, system_id="build", event_type="create_build", operator_id=7, group_ids=[5])

        rows, total = await AuditLogDao.get_audit_logs(["5"])

        assert total == 1
        assert rows[0].operator_id == 7


class TestServiceTenantBoundary:
    @pytest.fixture()
    def child_admin(self):
        return make_user_payload(user_id=77, is_admin=True, is_global_super=False)

    @pytest.fixture()
    def global_super(self):
        return make_user_payload(user_id=1, is_admin=True, is_global_super=True)

    async def _call(self, user, **kwargs):
        with (
            patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
            patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=2),
        ):
            return await AuditLogService.get_audit_log(
                user,
                group_ids=[],
                operator_ids=[],
                start_time=None,
                end_time=None,
                system_id=None,
                event_type=None,
                page=1,
                limit=20,
                **kwargs,
            )

    async def test_tenant_admin_cannot_reach_foreign_app(
        self, patch_audit_dao, audit_lookups, audit_session, child_admin
    ):
        audit_lookups.apps = [make_app(APP_B, name="Beta", slug="beta", tenant_id=3)]
        insert_audit(audit_session, action="app.stop", target_type="app", target_id=APP_B, tenant_id=3)

        resp = await self._call(child_admin, target_app_id=APP_B)

        assert resp.status_code == UnAuthorizedError.Code

    async def test_tenant_admin_reads_own_app(self, patch_audit_dao, audit_lookups, audit_session, child_admin):
        audit_lookups.apps = [make_app(APP_A, name="Alpha", slug="alpha", tenant_id=2)]
        insert_audit(audit_session, action="app.publish", target_type="app", target_id=APP_A, tenant_id=2)
        insert_audit(audit_session, action="app.stop", target_type="app", target_id=APP_B, tenant_id=2)

        resp = await self._call(child_admin, target_app_id=APP_A)

        assert resp["data"]["total"] == 1
        assert resp["data"]["data"][0]["app_slug"] == "alpha"

    async def test_global_super_reads_any_app(self, patch_audit_dao, audit_lookups, audit_session, global_super):
        audit_lookups.apps = [make_app(APP_B, name="Beta", slug="beta", tenant_id=3)]
        insert_audit(audit_session, action="app.stop", target_type="app", target_id=APP_B, tenant_id=3)

        resp = await self._call(global_super, target_app_id=APP_B)

        assert resp["data"]["total"] == 1
        assert audit_lookups.apps and resp["data"]["data"][0]["app_name"] == "Beta"


class TestDeletedAppSnapshot:
    async def test_deleted_app_rows_keep_name_snapshot_and_slug(self, patch_audit_dao, audit_lookups, audit_session):
        audit_lookups.apps = [make_app(APP_A, name="Alpha", slug="alpha", tenant_id=2, state="deleted")]
        insert_audit(audit_session, action="app.delete", target_type="app", target_id=APP_A, object_name="Alpha")
        user = make_user_payload(user_id=1, is_admin=True, is_global_super=True)

        with (
            patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
            patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=1),
        ):
            resp = await AuditLogService.get_audit_log(user, [], [], None, None, None, None, 1, 20, target_app_id=APP_A)

        row = resp["data"]["data"][0]
        assert row["app_state"] == "deleted"
        assert row["app_slug"] == "alpha"
        assert row["object_name"] == "Alpha"

    async def test_row_without_app_table_row_falls_back_to_snapshot(
        self, patch_audit_dao, audit_lookups, audit_session
    ):
        # The application row is gone entirely (compensation path); the audit
        # row's object_name is the only name left and must still be shown.
        insert_audit(
            audit_session,
            action="app.release.submit",
            target_type="app_version",
            target_id="ver-1",
            object_name="Ghost",
            audit_metadata={"app_id": "gone", "app_slug": "ghost", "version_no": 2},
        )
        user = make_user_payload(user_id=1, is_admin=True, is_global_super=True)

        with (
            patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
            patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=1),
        ):
            resp = await AuditLogService.get_audit_log(user, [], [], None, None, None, None, 1, 20)

        row = resp["data"]["data"][0]
        assert row["app_id"] == "gone"
        assert row["app_name"] == "Ghost"
        assert row["app_slug"] == "ghost"
        assert row["version_no"] == 2
        assert "audit_metadata" not in row
