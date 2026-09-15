"""T086a — the data-plane RPC over a real SQLite file (AC-56, design D10-C).

The database under test is a genuine ``app.db`` in the per-test data root,
created the way an application would create it (plain ``sqlite3``, WAL mode).
What the assertions pin:

* the answers are **typed** — tables, columns, keyed rows, before/after — and
  the API has no surface that accepts a statement, so DDL is not something the
  manager refuses, it is something it cannot say;
* row reads are **stably ordered** (the key is always the tiebreaker), so paging
  through a table neither duplicates nor drops a row;
* a row update touches **exactly one** row inside one short transaction, and
  leaves no lock behind — the app's own writer must never find the manager
  sitting on its database;
* the RPC is the **only** entry to the file: nothing else in the manager opens
  SQLite, and the backend-side twin (``test_app_data_service``) asserts the
  backend never does either.
"""

from __future__ import annotations

import inspect
import re
import sqlite3
from pathlib import Path

import pytest

from runtime_manager import appdb
from runtime_manager.appdb import BUSY_TIMEOUT_MS, AppDbService
from runtime_manager.errors import (
    DatabaseNotFoundError,
    DataBusyError,
    DataInvalidError,
    RowNotFoundError,
    TableNotFoundError,
)

APP_ID = "app-data-1"
DB_BASE = f"/v1/apps/{APP_ID}/db"


@pytest.fixture
def app_db(rtm_config) -> Path:
    """An application database with three shapes of table.

    ``users`` — INTEGER PRIMARY KEY (the common case); ``events`` — no declared
    key (addressed by rowid); ``pairs`` — composite key WITHOUT ROWID (readable,
    exportable, not editable).
    """
    path = rtm_config.app_data_dir(APP_ID) / "app.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, score REAL, avatar BLOB, note TEXT);
        CREATE TABLE events (kind TEXT, at INTEGER);
        CREATE TABLE pairs (a TEXT, b TEXT, v INTEGER, PRIMARY KEY (a, b)) WITHOUT ROWID;
        """
    )
    conn.executemany(
        "INSERT INTO users (id, name, score, avatar, note) VALUES (?, ?, ?, ?, ?)",
        [(i, f"user-{i:02d}", float(i % 3), b"\x00\x01" if i == 1 else None, None) for i in range(1, 8)],
    )
    conn.executemany("INSERT INTO events (kind, at) VALUES (?, ?)", [("a", 1), ("b", 2), ("a", 3)])
    conn.executemany("INSERT INTO pairs (a, b, v) VALUES (?, ?, ?)", [("x", "y", 1), ("x", "z", 2)])
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def service(rtm_config) -> AppDbService:
    return AppDbService(rtm_config)


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------


class TestListTablesAndSchema:
    def test_list_tables_and_schema(self, app_db, rtm_client):
        """AC-56 — user tables only, with the key each one is addressed by."""
        tables = rtm_client.get(f"{DB_BASE}/tables").json()["tables"]
        assert [table["name"] for table in tables] == ["events", "pairs", "users"]
        assert {table["name"]: table["column_count"] for table in tables} == {"events": 2, "pairs": 3, "users": 5}

        schema = rtm_client.get(f"{DB_BASE}/tables/users/schema").json()
        assert schema["table"] == "users"
        assert [column["name"] for column in schema["columns"]] == ["id", "name", "score", "avatar", "note"]
        assert schema["key"] == {"column": "id", "kind": "primary_key"}
        assert schema["editable"] is True
        by_name = {column["name"]: column for column in schema["columns"]}
        assert by_name["name"]["notnull"] is True
        assert by_name["avatar"]["editable"] is False, "a BLOB column cannot be edited as text"

        events = rtm_client.get(f"{DB_BASE}/tables/events/schema").json()
        assert events["key"] == {"column": "rowid", "kind": "rowid"}

        pairs = rtm_client.get(f"{DB_BASE}/tables/pairs/schema").json()
        assert pairs["editable"] is False, "a composite-key WITHOUT ROWID table has nothing that names one row"

    def test_sqlite_internal_tables_are_hidden(self, app_db, rtm_config, service):
        conn = sqlite3.connect(app_db)
        conn.execute("CREATE TABLE t_seq (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
        conn.commit()
        conn.close()
        names = [table["name"] for table in service.list_tables(APP_ID)]
        assert "sqlite_sequence" not in names
        assert "t_seq" in names

    def test_missing_database_is_404_not_created(self, rtm_config, rtm_client):
        """The app makes its own database; the manager never conjures an empty one."""
        response = rtm_client.get(f"{DB_BASE}/tables")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "db_not_found"
        assert not (rtm_config.app_data_dir(APP_ID) / "app.db").exists()

    def test_unknown_table_is_table_not_found(self, app_db, rtm_client):
        response = rtm_client.get(f"{DB_BASE}/tables/ghost/schema")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "table_not_found"


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------


class TestRows:
    def test_row_read_paginated_with_stable_order(self, app_db, rtm_client):
        """AC-56 — pages concatenate to the whole table, in the same order, every time.

        ``score`` has ties (0/1/2 repeating), which is exactly the input that
        makes an ``ORDER BY score`` alone non-deterministic; the key tiebreaker
        is what keeps page boundaries stable.
        """
        collected: list[int] = []
        for page in (1, 2, 3, 4):
            payload = rtm_client.get(f"{DB_BASE}/tables/users/rows", params={"page": page, "size": 2, "order": "score"})
            body = payload.json()
            assert body["total"] == 7
            assert body["page"] == page and body["size"] == 2
            collected.extend(row["key"] for row in body["rows"])
        assert sorted(collected) == list(range(1, 8)), "every row exactly once across the pages"

        whole = rtm_client.get(f"{DB_BASE}/tables/users/rows", params={"size": 200, "order": "score"}).json()
        assert [row["key"] for row in whole["rows"]] == collected, "paging must reproduce the unpaged order"
        scores = [row["values"]["score"] for row in whole["rows"]]
        assert scores == sorted(scores)
        for score in set(scores):
            keys = [row["key"] for row in whole["rows"] if row["values"]["score"] == score]
            assert keys == sorted(keys), "ties are broken by the key, ascending"

        descending = rtm_client.get(f"{DB_BASE}/tables/users/rows", params={"order": "-id"}).json()
        assert [row["key"] for row in descending["rows"]] == list(range(7, 0, -1))

    def test_rows_carry_values_and_blob_placeholder(self, app_db, rtm_client):
        body = rtm_client.get(f"{DB_BASE}/tables/users/rows", params={"size": 1}).json()
        row = body["rows"][0]
        assert row["key"] == 1
        assert row["values"]["name"] == "user-01"
        assert row["values"]["avatar"] == "<blob 2 bytes>", "binary is described, never dumped into JSON"

    def test_rowid_tables_are_keyed_by_rowid(self, app_db, rtm_client):
        body = rtm_client.get(f"{DB_BASE}/tables/events/rows").json()
        assert [row["key"] for row in body["rows"]] == [1, 2, 3]
        assert body["rows"][0]["values"] == {"kind": "a", "at": 1}

    def test_unknown_order_column_is_rejected(self, app_db, rtm_client):
        response = rtm_client.get(f"{DB_BASE}/tables/users/rows", params={"order": "ghost"})
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "data_invalid"


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_row_update_single_row_only(self, app_db, rtm_client):
        """AC-56 — one row, addressed by its key, with before/after for the audit trail."""
        response = rtm_client.patch(f"{DB_BASE}/tables/users/rows/3", {"values": {"name": "renamed", "note": "hi"}})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["table"] == "users" and body["key"] == 3
        assert body["before"] == {"name": "user-03", "note": None}
        assert body["after"] == {"name": "renamed", "note": "hi"}

        conn = sqlite3.connect(app_db)
        assert conn.execute("SELECT name FROM users WHERE id = 3").fetchone() == ("renamed",)
        assert conn.execute("SELECT COUNT(*) FROM users WHERE name = 'renamed'").fetchone() == (1,)
        assert conn.execute("SELECT name FROM users WHERE id = 4").fetchone() == ("user-04",), "neighbours untouched"
        conn.close()

    def test_update_by_rowid(self, app_db, rtm_client):
        response = rtm_client.patch(f"{DB_BASE}/tables/events/rows/2", {"values": {"kind": "z"}})
        assert response.status_code == 200, response.text
        conn = sqlite3.connect(app_db)
        assert conn.execute("SELECT kind FROM events ORDER BY rowid").fetchall() == [("a",), ("z",), ("a",)]
        conn.close()

    def test_missing_row_is_rejected_and_nothing_written(self, app_db, rtm_client, service):
        response = rtm_client.patch(f"{DB_BASE}/tables/users/rows/99", {"values": {"name": "x"}})
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "row_not_found"

        with pytest.raises(RowNotFoundError):
            service.update_row(APP_ID, "users", "99", {"name": "x"})

    def test_affected_rowcount_other_than_one_is_rolled_back(self, app_db, service, monkeypatch):
        """The rowcount guard is the last line: a key column that turns out non-unique
        (a rowid table whose 'id' is a plain column, say) must not become a mass update."""
        conn = sqlite3.connect(app_db)
        conn.execute("CREATE TABLE loose (id INTEGER, v TEXT)")
        conn.executemany("INSERT INTO loose VALUES (?, ?)", [(1, "a"), (1, "b")])
        conn.commit()
        conn.close()

        # `loose` has no declared key so it is addressed by rowid; force the
        # service to treat the non-unique `id` as the key to reach the guard.
        original = AppDbService._shape

        def _shape_with_loose_key(conn, table):
            shape = original(conn, table)
            if table == "loose":
                shape.key = "id"
            return shape

        monkeypatch.setattr(AppDbService, "_shape", staticmethod(_shape_with_loose_key))
        with pytest.raises(DataInvalidError, match="matches 2 rows"):
            service.update_row(APP_ID, "loose", "1", {"v": "changed"})

        conn = sqlite3.connect(app_db)
        assert conn.execute("SELECT v FROM loose ORDER BY rowid").fetchall() == [("a",), ("b",)]
        conn.close()

    @pytest.mark.parametrize(
        ("values", "fragment"),
        [
            ({"id": 9}, "row key"),
            ({"avatar": "x"}, "binary"),
            ({"ghost": 1}, "does not exist"),
            ({"name": {"nested": 1}}, "scalar"),
            ({}, "non-empty"),
        ],
    )
    def test_invalid_assignments_are_rejected(self, app_db, service, values, fragment):
        with pytest.raises(DataInvalidError, match=fragment):
            service.update_row(APP_ID, "users", "1", values)

    def test_composite_key_table_is_not_editable(self, app_db, service):
        with pytest.raises(DataInvalidError, match="single-column key"):
            service.update_row(APP_ID, "pairs", "x", {"v": 3})

    def test_constraint_violation_is_data_invalid_not_500(self, app_db, rtm_client):
        response = rtm_client.patch(f"{DB_BASE}/tables/users/rows/1", {"values": {"name": None}})
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "data_invalid"


# ---------------------------------------------------------------------------
# no DDL — by construction
# ---------------------------------------------------------------------------


class TestDdlStatementsRejected:
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
    def test_ddl_statements_rejected(self, app_db, rtm_client, service, table):
        """AC-56 — every identifier is checked against sqlite_master before it is quoted.

        A statement smuggled into a table name never reaches SQLite: it fails the
        identifier check (400) or the existence check (404). Either way the
        schema is what it was.
        """
        with pytest.raises((DataInvalidError, TableNotFoundError)):
            service.table_schema(APP_ID, table)
        with pytest.raises((DataInvalidError, TableNotFoundError)):
            service.rows(APP_ID, table)
        with pytest.raises((DataInvalidError, TableNotFoundError)):
            service.update_row(APP_ID, table, "1", {"name": "x"})
        with pytest.raises((DataInvalidError, TableNotFoundError)):
            service.export_csv(APP_ID, table)

        conn = sqlite3.connect(app_db)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names == {"users", "events", "pairs"}
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        conn.close()

    def test_order_and_column_names_cannot_carry_sql(self, app_db, service):
        with pytest.raises(DataInvalidError):
            service.rows(APP_ID, "users", order="id; DROP TABLE users")
        with pytest.raises(DataInvalidError):
            service.update_row(APP_ID, "users", "1", {"name = 'x' WHERE 1=1; --": "y"})

    def test_no_surface_accepts_a_statement(self):
        """There is no ``sql`` / ``query`` / ``statement`` parameter anywhere on the service or the router."""
        from runtime_manager.api import appdb as api

        banned = re.compile(r"sql|query|statement|execute|pragma", re.IGNORECASE)
        for owner in (AppDbService, api):
            for name, member in inspect.getmembers(owner, inspect.isfunction):
                if name.startswith("_") and owner is AppDbService:
                    continue
                for parameter in inspect.signature(member).parameters:
                    assert not banned.search(parameter), f"{owner.__name__}.{name}({parameter})"
        paths = {route.path for route in api.router.routes}
        assert paths == {
            "/v1/apps/{app_id}/db/tables",
            "/v1/apps/{app_id}/db/tables/{table}/schema",
            "/v1/apps/{app_id}/db/tables/{table}/rows",
            "/v1/apps/{app_id}/db/tables/{table}/rows/{key}",
            "/v1/apps/{app_id}/db/export",
        }
        methods = {(route.path, tuple(sorted(route.methods))) for route in api.router.routes}
        assert ("/v1/apps/{app_id}/db/tables/{table}/rows/{key}", ("PATCH",)) in methods
        assert not any("POST" in m or "DELETE" in m or "PUT" in m for _, m in methods), "no create / delete / replace"


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_produces_file_handle(self, app_db, rtm_client, rtm_config):
        """AC-56 — a CSV of the whole table, streamed as a file and cleaned up afterwards."""
        response = rtm_client.get(f"{DB_BASE}/export", params={"table": "users"})
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        assert 'filename="users.csv"' in response.headers["content-disposition"]
        lines = response.text.strip().splitlines()
        assert lines[0] == "id,name,score,avatar,note"
        assert len(lines) == 8
        assert lines[1].startswith("1,user-01,1.0,<blob 2 bytes>,")

        exports = rtm_config.data_root / "exports" / APP_ID
        assert not any(exports.glob("*.csv")), "the temp file is removed once the response has been sent"

    def test_export_unknown_table(self, app_db, rtm_client):
        response = rtm_client.get(f"{DB_BASE}/export", params={"table": "ghost"})
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "table_not_found"


# ---------------------------------------------------------------------------
# concurrency discipline
# ---------------------------------------------------------------------------


class TestShortTransactionAndBusyTimeout:
    def test_short_transaction_and_busy_timeout(self, app_db, service, monkeypatch):
        """AC-56 — every call opens its own connection with busy_timeout, and closes it.

        Proven two ways: the connections are tracked and each one is closed
        with no transaction open by the time the call returns; and after every
        call a second connection can take the write lock *immediately*, which
        it could not if the manager were still holding one.
        """
        opened: list[sqlite3.Connection] = []
        real_connect = sqlite3.connect

        def _tracking_connect(*args, **kwargs):
            assert kwargs.get("timeout") == BUSY_TIMEOUT_MS / 1000, "busy_timeout must be set on every connection"
            conn = real_connect(*args, **kwargs)
            opened.append(conn)
            return conn

        monkeypatch.setattr(appdb.sqlite3, "connect", _tracking_connect)

        def _writer_can_lock_now() -> None:
            probe = real_connect(app_db, timeout=0)
            try:
                probe.execute("BEGIN IMMEDIATE")
                probe.execute("ROLLBACK")
            finally:
                probe.close()

        service.list_tables(APP_ID)
        service.table_schema(APP_ID, "users")
        service.rows(APP_ID, "users", page=2, size=3, order="-score")
        service.update_row(APP_ID, "users", "2", {"note": "touched"})
        service.export_csv(APP_ID, "users")
        _writer_can_lock_now()

        assert len(opened) == 5, "one connection per call, none shared"
        for conn in opened:
            with pytest.raises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")  # closed

    def test_reads_open_the_file_read_only(self, app_db, service, monkeypatch):
        uris: list[str] = []
        real_connect = sqlite3.connect

        def _spy(database, *args, **kwargs):
            uris.append(database)
            return real_connect(database, *args, **kwargs)

        monkeypatch.setattr(appdb.sqlite3, "connect", _spy)
        service.list_tables(APP_ID)
        service.rows(APP_ID, "users")
        service.export_csv(APP_ID, "users")
        service.update_row(APP_ID, "users", "1", {"note": "w"})
        assert [uri.rsplit("?", 1)[1] for uri in uris] == ["mode=ro", "mode=ro", "mode=ro", "mode=rw"]
        assert not any("rwc" in uri for uri in uris), "never create the file on the app's behalf"

    def test_write_waits_then_reports_busy(self, app_db, service, monkeypatch):
        """A writer holding the lock past busy_timeout is a retryable ``data_busy``, not a 500."""
        monkeypatch.setattr(appdb, "BUSY_TIMEOUT_MS", 50)
        holder = sqlite3.connect(app_db)
        holder.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(DataBusyError):
                service.update_row(APP_ID, "users", "1", {"note": "blocked"})
        finally:
            holder.execute("ROLLBACK")
            holder.close()
        conn = sqlite3.connect(app_db)
        assert conn.execute("SELECT note FROM users WHERE id = 1").fetchone() == (None,)
        conn.close()


# ---------------------------------------------------------------------------
# single entry
# ---------------------------------------------------------------------------


class TestSingleEntry:
    def test_backend_never_opens_host_db_file(self):
        """AC-56 / D10-C — inside the manager, ``appdb.py`` is the only module touching SQLite.

        The backend half of this promise (no ``sqlite3`` import under
        ``bisheng/app_runtime``, every data call through ``orchestrator_client``)
        is ``test_app_data_service.py``; this side pins that the file has one
        reader in this process and that reader is reached through the HMAC RPC.
        """
        package = Path(appdb.__file__).parent
        offenders = [
            path.relative_to(package)
            for path in package.rglob("*.py")
            if path.name != "appdb.py" and re.search(r"^\s*(import|from)\s+sqlite3\b", path.read_text(), re.M)
        ]
        assert not offenders, offenders

        from runtime_manager.api import appdb as api

        for route in api.router.routes:
            dependency_names = {dependency.call.__name__ for dependency in route.dependant.dependencies}
            assert "verify_hmac" in dependency_names, route.path

    def test_db_path_rejects_traversal(self, rtm_config, service):
        with pytest.raises(DataInvalidError):
            service.db_path("../other")
        with pytest.raises(DatabaseNotFoundError):
            service.list_tables("no-such-app")
