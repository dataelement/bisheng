"""F056 T025 — system-audit export.

The export must be the list under a different pagination driver and nothing
else (spec 决议-8 / AC-32): same role gate, same tenant scope, same
projection. And no secret value may leave through it (AC-26) — the raw
``metadata`` blob is never emitted, only named derived fields.
"""

import json
from unittest.mock import patch

import pytest

from bisheng.api.services import audit_log as service_module
from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.errcode.http_error import UnAuthorizedError
from test.audit.conftest import insert_audit, make_app, make_user_payload

SECRET = "sk-live-THIS-MUST-NEVER-LEAVE"


@pytest.fixture()
def child_admin():
    return make_user_payload(user_id=77, is_admin=True, is_global_super=False)


@pytest.fixture()
def global_super():
    return make_user_payload(user_id=1, is_admin=True, is_global_super=True)


async def _export(user, *, current_tenant=2, **kwargs):
    with (
        patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
        patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=current_tenant),
    ):
        return await AuditLogService.export_audit_log(
            user,
            group_ids=[],
            operator_ids=[],
            start_time=None,
            end_time=None,
            system_id=None,
            event_type=None,
            **kwargs,
        )


class TestExportBoundary:
    async def test_child_admin_export_excludes_other_tenants(
        self, patch_audit_dao, audit_lookups, audit_session, child_admin
    ):
        insert_audit(audit_session, action="app.publish", tenant_id=2, operator_tenant_id=2)
        insert_audit(audit_session, action="app.stop", tenant_id=3, operator_tenant_id=3)
        insert_audit(audit_session, action="app.resume", tenant_id=3, operator_tenant_id=2)

        rows, total = await _export(child_admin)

        assert total == 2
        assert {r["action"] for r in rows} == {"app.publish", "app.resume"}

    async def test_child_admin_naming_other_tenant_is_rejected(self, patch_audit_dao, audit_lookups, child_admin):
        with pytest.raises(UnAuthorizedError):
            await _export(child_admin, tenant_id=3)

    async def test_super_export_narrows_by_tenant_id(self, patch_audit_dao, audit_lookups, audit_session, global_super):
        insert_audit(audit_session, action="app.publish", tenant_id=2, operator_tenant_id=2)
        insert_audit(audit_session, action="app.stop", tenant_id=3, operator_tenant_id=3)

        rows, total = await _export(global_super, current_tenant=1, tenant_id=3)

        assert total == 1 and rows[0]["action"] == "app.stop"

    async def test_plain_user_is_rejected(self, patch_audit_dao, audit_lookups, monkeypatch):
        user = make_user_payload(user_id=500, is_admin=False, is_global_super=False)

        async def _no_menu(_user):
            return False

        async def _no_groups(_uid):
            return []

        monkeypatch.setattr(AuditLogService, "_user_has_log_web_menu", _no_menu)
        monkeypatch.setattr("bisheng.api.services.audit_log.UserGroupDao.aget_user_admin_group", _no_groups)
        with pytest.raises(UnAuthorizedError):
            await _export(user)


class TestExportContent:
    async def test_no_metadata_blob_and_no_secret_in_output(
        self, patch_audit_dao, audit_lookups, audit_session, global_super
    ):
        audit_lookups.apps = [make_app("app-1", name="Alpha", slug="alpha", tenant_id=2, owner_user_id=7)]
        audit_lookups.users = [type("U", (), {"user_id": 7, "user_name": "owner-olga"})()]
        insert_audit(
            audit_session,
            action="app.release.submit",
            operator_id=0,
            operator_name="ci-bot",
            target_type="app_version",
            target_id="ver-1",
            tenant_id=2,
            audit_metadata={
                "app_id": "app-1",
                "version_no": 4,
                "operator": {"kind": "service_account", "name": "ci-bot", "key_mask": "bsk_****ab12"},
                "raw_key": SECRET,
            },
        )

        rows, total = await _export(global_super, current_tenant=1)

        assert total == 1
        row = rows[0]
        assert "audit_metadata" not in row and "metadata" not in row
        assert SECRET not in json.dumps(row, default=str)
        assert row["operator_kind"] == "service_account"
        assert row["operator_key_mask"] == "bsk_****ab12"
        assert row["app_owner_name"] == "owner-olga"
        assert row["app_slug"] == "alpha" and row["version_no"] == 4

    async def test_service_account_convention_without_explicit_kind(
        self, patch_audit_dao, audit_lookups, audit_session, global_super
    ):
        # beta2 convention: operator 0 + a name is a service account; operator
        # 0 + "system" is a system trigger.
        insert_audit(audit_session, action="app.release.submit", operator_id=0, operator_name="ci-bot", tenant_id=2)
        insert_audit(audit_session, action="app.release.online", operator_id=0, operator_name="system", tenant_id=2)
        insert_audit(audit_session, action="app.publish", operator_id=9, operator_name="olga", tenant_id=2)

        rows, _ = await _export(global_super, current_tenant=1)

        kinds = {r["operator_name"]: r["operator_kind"] for r in rows}
        assert kinds == {"ci-bot": "service_account", "system": None, "olga": None}
        assert all(r["operator_key_mask"] is None for r in rows)

    async def test_tenant_name_is_resolved(self, patch_audit_dao, audit_lookups, audit_session, global_super):
        audit_lookups.tenants = [type("T", (), {"id": 2, "tenant_name": "Acme"})()]
        insert_audit(audit_session, action="app.publish", tenant_id=2)

        rows, _ = await _export(global_super, current_tenant=1)

        assert rows[0]["tenant_name"] == "Acme"

    async def test_walks_pages_and_caps(self, patch_audit_dao, audit_lookups, audit_session, global_super, monkeypatch):
        monkeypatch.setattr(service_module, "AUDIT_EXPORT_PAGE_SIZE", 2)
        monkeypatch.setattr(service_module, "AUDIT_EXPORT_MAX_ROWS", 5)
        for i in range(7):
            insert_audit(audit_session, action="app.publish", tenant_id=2, note=str(i))

        rows, total = await _export(global_super, current_tenant=1)

        assert total == 7
        assert len(rows) == 5
        assert len({r["id"] for r in rows}) == 5
