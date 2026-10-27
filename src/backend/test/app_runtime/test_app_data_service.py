"""T087a — ``AppDataService``: owner narrowing, audit, forwarding (AC-56, AC-65).

The service is the single door to an application's own data. Every test here
runs against the in-memory database and the programmable orchestrator stub;
what is asserted is (who got in, what RPC left, what audit row was written) —
never how the manager reads the file, which is ``runtime-manager``'s own suite.

Two of the cases are structural rather than behavioural, and they are the ones
that keep the promise honest over time: no module under ``bisheng`` opens
SQLite or calls ``orchestrator_client.db_*`` except this service, so the F052
MCP data tools *cannot* grow a second path around the owner rule and the audit
row without failing here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bisheng.app_runtime.domain.constants import AppAuditAction, AppState
from bisheng.common.errcode.app_factory import (
    AppDataForbiddenError,
    AppDataInvalidError,
    AppNotFoundError,
)

pytestmark = pytest.mark.usefixtures("app_db", "fake_orchestrator")

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "bisheng"
SERVICE_FILE = BACKEND_ROOT / "app_runtime" / "domain" / "services" / "app_data_service.py"
CLIENT_FILE = BACKEND_ROOT / "app_runtime" / "domain" / "services" / "orchestrator_client.py"


def _super_admin_payload(user_id: int = 90999):
    from bisheng.common.dependencies.user_deps import UserPayload

    return UserPayload(user_id=user_id, user_name="f054-super", user_role=[], tenant_id=1, is_global_super=True)


# ---------------------------------------------------------------------------
# owner narrowing
# ---------------------------------------------------------------------------


class TestOwnerOnly:
    async def test_owner_only_business_rule_precheck(
        self, app_factory, app_owner, normal_user, tenant_admin_payload, tenant_admins, fake_orchestrator
    ):
        """AC-56 — owner passes; tenant administrator **and** platform super admin are refused.

        A business pre-check, not a permission-runtime verdict: the runtime
        short-circuits administrators to ALLOW, so the rule has to be checked
        here, and it has to be checked *before* any RPC leaves — a refused
        caller must not even learn whether the app has tables.
        """
        from bisheng.app_runtime.domain.services.app_data_service import AppDataService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        tenant_admins.grant(tenant_admin_payload.user_id, app.tenant_id)

        for refused in (normal_user.payload, tenant_admin_payload, _super_admin_payload()):
            with pytest.raises(AppDataForbiddenError) as excinfo:
                await AppDataService.list_tables(app.id, actor=refused)
            assert excinfo.value.code == 16162
            with pytest.raises(AppDataForbiddenError):
                await AppDataService.update_row(app.id, "users", "1", {"name": "x"}, actor=refused)
            with pytest.raises(AppDataForbiddenError):
                await AppDataService.export_table(app.id, "users", actor=refused)
        assert fake_orchestrator.calls == [], "a refusal never reaches the manager"

        tables = await AppDataService.list_tables(app.id, actor=app_owner.payload)
        assert tables == fake_orchestrator.responses["db_tables"]
        assert fake_orchestrator.calls == [("db_tables", {"app_id": app.id})]

    async def test_deleted_app_answers_not_found_to_everyone(self, app_factory, app_owner, normal_user):
        """A stranger and the owner get the same 16101 — the refusal leaks nothing."""
        from bisheng.app_runtime.domain.services.app_data_service import AppDataService

        app, _ = await app_factory(state=AppState.DELETED.value)
        for actor in (app_owner.payload, normal_user.payload):
            with pytest.raises(AppNotFoundError):
                await AppDataService.list_tables(app.id, actor=actor)

    async def test_non_owner_gets_16162_not_403(self, api_app, app_factory, normal_user, tenant_admin_payload):
        """Design pit 25 — a real 403 on a GET sends the platform SPA to ``/403``.

        The refusal rides inside a 200 envelope with business code 16162, so
        the data tab renders a notice and the detail page stays where it is.
        """
        app, _ = await app_factory(state=AppState.ONLINE.value)
        for payload in (normal_user.payload, tenant_admin_payload):
            async with api_app(payload) as client:
                for path in (
                    f"/api/v1/apps/{app.id}/data/tables",
                    f"/api/v1/apps/{app.id}/data/tables/users/schema",
                    f"/api/v1/apps/{app.id}/data/tables/users/rows",
                    f"/api/v1/apps/{app.id}/data/export?table=users",
                ):
                    response = await client.get(path)
                    assert response.status_code == 200, path
                    assert response.json()["status_code"] == 16162, path
                response = await client.patch(
                    f"/api/v1/apps/{app.id}/data/tables/users/rows/1", json={"values": {"name": "x"}}
                )
                assert response.status_code == 200
                assert response.json()["status_code"] == 16162


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


class TestAudit:
    async def test_row_edit_audited_with_before_after(self, app_factory, app_owner, fake_orchestrator, audit_sink):
        """AC-56 / AC-65 — ``app.data_row_edit`` carries table, key, before and after.

        ``before`` / ``after`` come from the manager's own transaction, not
        from a second read that the app's next write could already have
        overtaken.
        """
        from bisheng.app_runtime.domain.services.app_data_service import AppDataService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        fake_orchestrator.responses["db_update_row"] = {
            "table": "users",
            "key": 7,
            "before": {"name": "alice", "note": None},
            "after": {"name": "bob", "note": "hi"},
        }

        result = await AppDataService.update_row(
            app.id, "users", "7", {"name": "bob", "note": "hi"}, actor=app_owner.payload
        )

        assert result["after"] == {"name": "bob", "note": "hi"}
        assert fake_orchestrator.calls == [
            ("db_update_row", {"app_id": app.id, "table": "users", "key": "7", "values": {"name": "bob", "note": "hi"}})
        ]
        assert [row["action"] for row in audit_sink] == [AppAuditAction.DATA_ROW_EDIT.value]
        row = audit_sink[0]
        assert row["target_type"] == "app" and row["target_id"] == app.id
        assert row["operator_id"] == app_owner.user_id
        assert row["tenant_id"] == app.tenant_id
        assert row["metadata"]["table"] == "users"
        assert row["metadata"]["key"] == 7
        assert row["metadata"]["before"] == {"name": "alice", "note": None}
        assert row["metadata"]["after"] == {"name": "bob", "note": "hi"}
        assert row["metadata"]["columns"] == ["name", "note"]

    async def test_export_is_audited_and_returns_csv_bytes(self, app_factory, app_owner, fake_orchestrator, audit_sink):
        """AC-65 — a whole table leaving the platform is an event, even though nothing changed."""
        from bisheng.app_runtime.domain.services.app_data_service import AppDataService

        app, _ = await app_factory(state=AppState.ONLINE.value, slug="sales")
        filename, content = await AppDataService.export_table(app.id, "users", actor=app_owner.payload)

        assert filename == "sales-users.csv"
        assert content == fake_orchestrator.responses["db_export"]
        assert fake_orchestrator.calls == [("db_export", {"app_id": app.id, "table": "users"})]
        assert [row["action"] for row in audit_sink] == [AppAuditAction.DATA_EXPORT.value]
        assert audit_sink[0]["metadata"]["table"] == "users"
        assert audit_sink[0]["metadata"]["bytes"] == len(content)

    async def test_export_endpoint_answers_a_file(self, api_app, app_factory, app_owner, fake_orchestrator, audit_sink):
        app, _ = await app_factory(state=AppState.ONLINE.value, slug="sales")
        async with api_app(app_owner.payload) as client:
            response = await client.get(f"/api/v1/apps/{app.id}/data/export?table=users")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "sales-users.csv" in response.headers["content-disposition"]
        assert response.content == fake_orchestrator.responses["db_export"]
        assert [row["action"] for row in audit_sink] == [AppAuditAction.DATA_EXPORT.value]

    async def test_reads_are_not_audited(self, app_factory, app_owner, audit_sink):
        """Viewing is not an event; only edits and exports are (AC-65)."""
        from bisheng.app_runtime.domain.services.app_data_service import AppDataService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        await AppDataService.list_tables(app.id, actor=app_owner.payload)
        await AppDataService.get_table_schema(app.id, "users", actor=app_owner.payload)
        await AppDataService.get_rows(app.id, "users", actor=app_owner.payload, page=2, size=10, order="-id")
        assert audit_sink == []


# ---------------------------------------------------------------------------
# no DDL — checked here too
# ---------------------------------------------------------------------------


class TestDdlRejectedAtBackendLayerToo:
    @pytest.mark.parametrize(
        "table",
        [
            "users; DROP TABLE users",
            'users" ; DROP TABLE users; --',
            "sqlite_master",
            "PRAGMA journal_mode",
            "CREATE TABLE x(a)",
            "../users",
            "",
        ],
    )
    async def test_ddl_rejected_at_backend_layer_too(self, app_factory, app_owner, fake_orchestrator, table):
        """AC-56 — the manager checks names against the live schema; backend refuses
        anything that is not a plain identifier before the request even leaves."""
        from bisheng.app_runtime.domain.services.app_data_service import AppDataService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        actor = app_owner.payload
        with pytest.raises(AppDataInvalidError):
            await AppDataService.get_table_schema(app.id, table, actor=actor)
        with pytest.raises(AppDataInvalidError):
            await AppDataService.get_rows(app.id, table, actor=actor)
        with pytest.raises(AppDataInvalidError):
            await AppDataService.update_row(app.id, table, "1", {"name": "x"}, actor=actor)
        with pytest.raises(AppDataInvalidError):
            await AppDataService.export_table(app.id, table, actor=actor)
        assert fake_orchestrator.calls == [], "a rejected identifier never reaches the manager"

    async def test_columns_order_and_values_are_checked(self, app_factory, app_owner, fake_orchestrator):
        from bisheng.app_runtime.domain.services.app_data_service import AppDataService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        actor = app_owner.payload
        with pytest.raises(AppDataInvalidError):
            await AppDataService.get_rows(app.id, "users", actor=actor, order="id; DROP TABLE users")
        with pytest.raises(AppDataInvalidError):
            await AppDataService.update_row(app.id, "users", "1", {"name = 'x'; --": "y"}, actor=actor)
        with pytest.raises(AppDataInvalidError):
            await AppDataService.update_row(app.id, "users", "1", {"name": {"nested": True}}, actor=actor)
        with pytest.raises(AppDataInvalidError):
            await AppDataService.update_row(app.id, "users", "1", {}, actor=actor)
        with pytest.raises(AppDataInvalidError):
            await AppDataService.update_row(app.id, "users", "a/b", {"name": "x"}, actor=actor)
        with pytest.raises(AppDataInvalidError):
            await AppDataService.get_rows(app.id, "users", actor=actor, size=10_000)
        assert fake_orchestrator.calls == []


# ---------------------------------------------------------------------------
# single implementation, RPC only
# ---------------------------------------------------------------------------


class TestForwardsToManagerOnly:
    async def test_forwards_to_manager_only_never_opens_db_file(
        self, app_factory, app_owner, fake_orchestrator, monkeypatch
    ):
        """AC-56 / D10-C — every call is exactly one ``db_*`` RPC; no file is opened.

        The database lives on the manager's host; backend does not know that
        path (K1) and in the multi-node shape is not on that machine. A
        ``sqlite3.connect`` here would only ever work on a single-host box —
        which is the kind of bug the constitution's C8 exists to catch.
        """
        import sqlite3

        from bisheng.app_runtime.domain.services.app_data_service import AppDataService

        def _forbidden(*args, **kwargs):
            raise AssertionError("backend must never open the app's database file")

        monkeypatch.setattr(sqlite3, "connect", _forbidden)

        app, _ = await app_factory(state=AppState.ONLINE.value)
        actor = app_owner.payload
        await AppDataService.list_tables(app.id, actor=actor)
        await AppDataService.get_table_schema(app.id, "users", actor=actor)
        await AppDataService.get_rows(app.id, "users", actor=actor, page=3, size=20, order="name")
        await AppDataService.update_row(app.id, "users", "1", {"name": "bob"}, actor=actor)
        await AppDataService.export_table(app.id, "users", actor=actor)

        assert fake_orchestrator.calls == [
            ("db_tables", {"app_id": app.id}),
            ("db_schema", {"app_id": app.id, "table": "users"}),
            ("db_rows", {"app_id": app.id, "table": "users", "page": 3, "size": 20, "order": "name"}),
            ("db_update_row", {"app_id": app.id, "table": "users", "key": "1", "values": {"name": "bob"}}),
            ("db_export", {"app_id": app.id, "table": "users"}),
        ]

    def test_backend_never_imports_sqlite_for_app_data(self):
        """Static half of the promise above: no ``sqlite3`` anywhere under ``app_runtime``."""
        pattern = re.compile(r"^\s*(?:from|import)\s+(?:sqlite3|aiosqlite)\b", re.M)
        offenders = [
            str(path.relative_to(BACKEND_ROOT))
            for path in (BACKEND_ROOT / "app_runtime").rglob("*.py")
            if pattern.search(path.read_text(encoding="utf-8"))
        ]
        assert not offenders, offenders

    def test_mcp_face_reuses_same_service_method(self):
        """AC-56 — ``AppDataService`` is the *only* caller of ``orchestrator_client.db_*``.

        F052's MCP data tools (and anything else) must go through the service
        so that owner narrowing and the audit row hold for every door. A
        second call site anywhere under ``bisheng`` fails here.
        """
        pattern = re.compile(r"orchestrator_client\s*\.\s*db_\w+")
        callers = sorted(
            str(path.relative_to(BACKEND_ROOT))
            for path in BACKEND_ROOT.rglob("*.py")
            if path != CLIENT_FILE and pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
        )
        assert callers == [str(SERVICE_FILE.relative_to(BACKEND_ROOT))], callers

        # And the service exposes the five operations by name, so the MCP
        # face has a method to call for each RPC rather than a reason to
        # reach past it.
        from bisheng.app_runtime.domain.services.app_data_service import AppDataService

        for name in ("list_tables", "get_table_schema", "get_rows", "update_row", "export_table"):
            assert callable(getattr(AppDataService, name)), name
