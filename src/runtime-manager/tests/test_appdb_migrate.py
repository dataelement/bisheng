"""T062 — declared-table migration and the pre-migration snapshot (F055 AC-42).

The platform declares tables in ``bisheng-app.yaml`` and the platform builds
them (DEV-07 ②); this is the half that actually issues the DDL, and the half
that has to keep a promise before it does: **a plan that can lose production
rows takes a snapshot first, or it does not run at all.**

What the assertions are about, in the order they matter:

* the snapshot exists in the object store **before** the first statement runs,
  it is a real SQLite database inside the tar (not a half-written WAL file),
  and it lands under ``apps/{app_id}/db-snapshots/`` in the private bucket;
* a snapshot that cannot be stored **refuses the migration** — the failure mode
  a naive implementation has is "log a warning and migrate anyway", which is
  indistinguishable from success right up to the moment somebody needs the
  snapshot;
* additive plans (new table, new column) never ask anybody anything and never
  take a snapshot, because there is nothing at risk;
* a plan is one transaction: the second half failing leaves the first half
  unapplied;
* nothing on this endpoint can carry SQL — a table name, a column name or a
  declared type that is really a statement is refused before the file is
  opened.
"""

from __future__ import annotations

import sqlite3
import tarfile
from io import BytesIO
from pathlib import Path

import pytest

from runtime_manager.appdb import (
    SNAPSHOT_MEMBER,
    AppDbSchemaService,
)
from runtime_manager.errors import SchemaMigrationFailedError

APP_ID = "app-migrate-1"
MIGRATE_PATH = "/v1/intents/db-migrate"


def _column(name: str, type_: str | None = "TEXT", **extra):
    return {"name": name, "type": type_, **extra}


@pytest.fixture
def service(rtm_config, fake_object_store) -> AppDbSchemaService:
    return AppDbSchemaService(rtm_config, store=fake_object_store)


@pytest.fixture
def db_path(rtm_config) -> Path:
    return rtm_config.app_data_dir(APP_ID) / "app.db"


@pytest.fixture
def live_db(db_path: Path) -> Path:
    """An application database with production rows in it, WAL like the real one."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, buyer TEXT NOT NULL, note TEXT)")
    conn.executemany("INSERT INTO orders (id, buyer, note) VALUES (?, ?, ?)", [(1, "alice", "x"), (2, "bob", None)])
    conn.commit()
    conn.close()
    return db_path


def _shape(path: Path, table: str) -> list[tuple[str, str, int]]:
    conn = sqlite3.connect(path)
    try:
        return [(row[1], row[2], row[3]) for row in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


def _rows(path: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# the platform builds the tables (DEV-07 ②)
# ---------------------------------------------------------------------------


class TestPlatformCreatesDeclaredTables:
    def test_first_release_creates_the_database_and_its_tables(self, service, db_path, fake_object_store):
        """No app has run yet, so there is no file — creating it is the job.

        Everywhere else in the manager the app owns its own file and we refuse
        to invent one (``mode=rw``); here the declaration *is* the instruction
        to build it, and a first release must not have to start the app once to
        get its tables.
        """
        assert not db_path.exists()

        result = service.migrate(
            APP_ID,
            [
                {
                    "op": "create_table",
                    "table": "orders",
                    "columns": [
                        _column("id", "INTEGER", primary_key=True),
                        _column("buyer", "TEXT", nullable=False),
                    ],
                }
            ],
        )

        assert result["snapshot_key"] is None, "a database we just created has no production data to preserve"
        assert [item["op"] for item in result["applied"]] == ["create_table"]
        assert _shape(db_path, "orders") == [("id", "INTEGER", 0), ("buyer", "TEXT", 1)]

    def test_adding_a_column_migrates_without_asking(self, service, live_db, fake_object_store):
        """AC-42 first half: additive, automatic, and no snapshot — nothing is at risk."""
        result = service.migrate(
            APP_ID,
            [{"op": "add_columns", "table": "orders", "columns": [_column("channel", "TEXT", default="web")]}],
        )

        assert result["snapshot_key"] is None
        assert result["applied"] == [{"op": "add_columns", "table": "orders", "columns": ["channel"]}]
        assert _rows(live_db, "SELECT id, channel FROM orders ORDER BY id") == [(1, "web"), (2, "web")]
        assert fake_object_store.calls_of("put_object") == []

    def test_replaying_the_same_plan_changes_nothing(self, service, live_db):
        """``manual_publish`` retries the same version, so the same plan arrives twice."""
        plan = [{"op": "add_columns", "table": "orders", "columns": [_column("channel", "TEXT")]}]
        service.migrate(APP_ID, plan)

        second = service.migrate(APP_ID, plan)

        assert second["applied"] == []
        assert second["skipped"] == [{"op": "add_columns", "table": "orders", "skipped": "exists"}]

    def test_an_add_columns_plan_builds_a_table_that_is_not_there_yet(self, service, live_db):
        """The plan's verb comes from two *declarations*; the database may disagree.

        An application that went online before the platform built tables has a
        file whose shape nobody here decided. The next release adds a column and
        the platform derives ``add_columns`` — for a table that does not exist.
        Every plan entry therefore carries the **full target shape**, and this
        test is what stops it shrinking back to the delta: a one-column
        ``orders`` table would pass every other assertion in this file and break
        the application at its first query.
        """
        result = service.migrate(
            APP_ID,
            [
                {
                    "op": "add_columns",
                    "table": "invoices",
                    "columns": [
                        _column("id", "INTEGER", primary_key=True),
                        _column("buyer", "TEXT", nullable=False),
                        _column("channel", "TEXT"),
                    ],
                }
            ],
        )

        assert [item["op"] for item in result["applied"]] == ["create_table"]
        assert [name for name, _, _ in _shape(live_db, "invoices")] == ["id", "buyer", "channel"]

    def test_a_declared_table_that_the_app_already_built_is_left_alone(self, service, live_db):
        """Apps create their own tables today (``CREATE TABLE IF NOT EXISTS``).

        Re-creating one would be a silent data loss; the platform's job is to
        make the declared shape exist, not to own the file.
        """
        result = service.migrate(
            APP_ID,
            [{"op": "create_table", "table": "orders", "columns": [_column("id", "INTEGER")]}],
        )

        assert result["skipped"] == [{"op": "create_table", "table": "orders", "skipped": "exists"}]
        assert _rows(live_db, "SELECT COUNT(*) FROM orders") == [(2,)]

    def test_a_new_not_null_column_without_a_default_is_refused(self, service, live_db):
        """Existing rows have no value for it — SQLite says so and so do we, first.

        Refused rather than relaxed to nullable: the manifest is the contract
        the application's own code reads, and a column that is NOT NULL there
        and nullable in production fails much later and much further away.
        """
        with pytest.raises(SchemaMigrationFailedError) as excinfo:
            service.migrate(
                APP_ID,
                [{"op": "add_columns", "table": "orders", "columns": [_column("owner", "TEXT", nullable=False)]}],
            )

        assert excinfo.value.detail["reason"] == "notnull_without_default"
        assert excinfo.value.detail["column"] == "owner"
        assert [name for name, _, _ in _shape(live_db, "orders")] == ["id", "buyer", "note"]


# ---------------------------------------------------------------------------
# the snapshot — AC-42's hard promise
# ---------------------------------------------------------------------------


class TestPreMigrationSnapshot:
    def test_dropping_a_column_snapshots_the_production_data_first(self, service, live_db, fake_object_store):
        result = service.migrate(
            APP_ID,
            [
                {
                    "op": "rebuild_table",
                    "table": "orders",
                    "columns": [_column("id", "INTEGER", primary_key=True), _column("buyer", "TEXT", nullable=False)],
                }
            ],
        )

        key = result["snapshot_key"]
        assert key is not None and key.startswith(f"apps/{APP_ID}/db-snapshots/") and key.endswith(".tar")
        # The dropped column is gone from the live database and the rows that
        # survive it are intact — that pair is what "breaking but confirmed" means.
        assert [name for name, _, _ in _shape(live_db, "orders")] == ["id", "buyer"]
        assert _rows(live_db, "SELECT id, buyer FROM orders ORDER BY id") == [(1, "alice"), (2, "bob")]

    def test_the_snapshot_is_a_readable_database_holding_the_old_shape(self, service, live_db, fake_object_store):
        """Not a tar of the live file: that is half of a WAL database and would
        not open. ``Connection.backup`` is what makes the copy consistent."""
        result = service.migrate(
            APP_ID,
            [{"op": "rebuild_table", "table": "orders", "columns": [_column("id", "INTEGER", primary_key=True)]}],
        )

        stored = fake_object_store.buckets["bisheng-apps"][result["snapshot_key"]]
        with tarfile.open(fileobj=BytesIO(stored.data)) as tar:
            assert tar.getnames() == [SNAPSHOT_MEMBER]
            payload = tar.extractfile(SNAPSHOT_MEMBER).read()
        restored = Path(live_db.parent / "restored.db")
        restored.write_bytes(payload)

        assert [name for name, _, _ in _shape(restored, "orders")] == ["id", "buyer", "note"]
        assert _rows(restored, "SELECT id, buyer FROM orders ORDER BY id") == [(1, "alice"), (2, "bob")]

    def test_the_snapshot_goes_to_the_private_bucket_and_writes_no_policy(self, service, live_db, fake_object_store):
        """Pit 20 — the platform's public bucket is nginx-reachable for any key."""
        service.migrate(APP_ID, [{"op": "drop_table", "table": "orders"}])

        put = fake_object_store.calls_of("put_object")
        assert [call["bucket"] for call in put] == ["bisheng-apps"]
        assert fake_object_store.policies == {}

    def test_a_snapshot_that_cannot_be_stored_refuses_the_migration(self, service, live_db, fake_object_store):
        """The failure mode worth a test of its own.

        "Warn and migrate anyway" looks identical to success until the day the
        snapshot is needed, and by then the rows are gone. So the release fails
        instead, and the owner still has their data.
        """
        fake_object_store.reachable = False

        with pytest.raises(SchemaMigrationFailedError) as excinfo:
            service.migrate(
                APP_ID,
                [{"op": "rebuild_table", "table": "orders", "columns": [_column("id", "INTEGER", primary_key=True)]}],
            )

        assert excinfo.value.detail["reason"] == "snapshot_failed"
        assert [name for name, _, _ in _shape(live_db, "orders")] == ["id", "buyer", "note"]
        assert _rows(live_db, "SELECT COUNT(*) FROM orders") == [(2,)]

    def test_the_caller_can_ask_for_a_snapshot_an_additive_plan_would_not_take(
        self, service, live_db, fake_object_store
    ):
        """``snapshot=True`` only ever *adds* one; the plan decides when it is mandatory."""
        result = service.migrate(
            APP_ID,
            [{"op": "add_columns", "table": "orders", "columns": [_column("channel", "TEXT")]}],
            snapshot=True,
        )

        assert result["snapshot_key"] is not None, "the caller asked, so it was taken"

    def test_a_destructive_plan_snapshots_even_when_the_caller_forgot(self, service, live_db, fake_object_store):
        result = service.migrate(APP_ID, [{"op": "drop_table", "table": "orders"}], snapshot=False)

        assert result["snapshot_key"] is not None


# ---------------------------------------------------------------------------
# one transaction, and no SQL on the wire
# ---------------------------------------------------------------------------


class TestPlanIsAtomicAndDeclarative:
    def test_a_plan_that_fails_half_way_applies_none_of_it(self, service, live_db):
        plan = [
            {"op": "add_columns", "table": "orders", "columns": [_column("channel", "TEXT")]},
            {"op": "add_columns", "table": "orders", "columns": [_column("owner", "TEXT", nullable=False)]},
        ]

        with pytest.raises(SchemaMigrationFailedError):
            service.migrate(APP_ID, plan)

        assert [name for name, _, _ in _shape(live_db, "orders")] == ["id", "buyer", "note"]

    @pytest.mark.parametrize(
        "plan",
        [
            [{"op": "drop_table", "table": "orders; DROP TABLE orders"}],
            [{"op": "create_table", "table": "sqlite_master", "columns": [{"name": "a"}]}],
            [{"op": "add_columns", "table": "orders", "columns": [{"name": "x = 1; --"}]}],
            [{"op": "add_columns", "table": "orders", "columns": [_column("x", "TEXT); DROP TABLE orders; --")]}],
            [{"op": "vacuum", "table": "orders"}],
        ],
    )
    def test_no_plan_entry_can_carry_a_statement(self, service, live_db, plan):
        """Identifiers and declared types are checked before the file is opened.

        The type check is the one that is easy to forget: ``type`` is the only
        free-text field that has to be *quoted into* the DDL rather than bound,
        so it gets the same treatment as a name.
        """
        with pytest.raises(SchemaMigrationFailedError) as excinfo:
            service.migrate(APP_ID, plan)

        assert excinfo.value.detail["reason"] in {"invalid_plan", "invalid_identifier", "invalid_type"}
        assert _rows(live_db, "SELECT COUNT(*) FROM orders") == [(2,)]

    def test_a_default_value_is_quoted_not_concatenated(self, service, live_db):
        service.migrate(
            APP_ID,
            [{"op": "add_columns", "table": "orders", "columns": [_column("note2", "TEXT", default="it's fine")]}],
        )

        assert _rows(live_db, "SELECT DISTINCT note2 FROM orders") == [("it's fine",)]

    def test_an_empty_plan_does_not_even_open_the_file(self, service, db_path):
        assert service.migrate(APP_ID, []) == {"applied": [], "skipped": [], "snapshot_key": None}
        assert not db_path.exists()


# ---------------------------------------------------------------------------
# the RPC
# ---------------------------------------------------------------------------


class TestMigrateRpc:
    def test_intent_route_applies_the_plan(self, rtm_client, rtm_config, fake_object_store, live_db):
        response = rtm_client.post(
            MIGRATE_PATH,
            {
                "app_id": APP_ID,
                "plan": [{"op": "add_columns", "table": "orders", "columns": [_column("channel", "TEXT")]}],
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["applied"] == [{"op": "add_columns", "table": "orders", "columns": ["channel"]}]

    def test_unsigned_request_is_rejected(self, rtm_client, live_db):
        response = rtm_client.post(MIGRATE_PATH, {"app_id": APP_ID, "plan": []}, sign=False)

        assert response.status_code == 401

    def test_failure_answers_the_platform_a_machine_code(self, rtm_client, live_db):
        response = rtm_client.post(
            MIGRATE_PATH,
            {
                "app_id": APP_ID,
                "plan": [{"op": "add_columns", "table": "orders", "columns": [_column("o", "TEXT", nullable=False)]}],
            },
        )

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "schema_migration_failed"
        assert detail["reason"] == "notnull_without_default"

    def test_the_data_plane_still_has_no_write_route(self):
        """The migration lives under ``/intents`` precisely so this stays true."""
        from runtime_manager.api import appdb as data_plane

        methods = {method for route in data_plane.router.routes for method in route.methods}
        assert methods == {"GET", "PATCH"}
