"""
DaMeng (达梦) Feasibility Validation Script
============================================
Run on a machine with dmPython + sqlalchemy-dm installed:

    uv run python scripts/dm_feasibility_check.py \
        --url "dm+dmPython://SYSDBA:password@192.168.107.9:5236/BISHENG"

Checks every MySQL→DaMeng substitution in the design spec and prints a
pass/fail report so we know what works before writing implementation code.
"""

import argparse
import sys
import textwrap
import traceback
from dataclasses import dataclass, field
from typing import Callable

import sqlalchemy as sa
from sqlalchemy import inspect, text

# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    error: str = ""


@dataclass
class Report:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    def print(self) -> None:
        print("\n" + "=" * 65)
        print("  DaMeng Feasibility Report")
        print("=" * 65)
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            mark = "✓" if r.passed else "✗"
            print(f"\n[{status}] {mark} {r.name}")
            if r.detail:
                for line in textwrap.wrap(r.detail, width=60, initial_indent="       "):
                    print(line)
            if r.error:
                print(f"       ERROR: {r.error[:200]}")
        print("\n" + "-" * 65)
        print(f"  Result: {passed}/{total} checks passed")
        print("=" * 65 + "\n")
        if passed < total:
            sys.exit(1)


def check(report: Report, name: str, fn: Callable[[], str]) -> None:
    """Run fn(); record pass with its return value as detail, or fail with traceback."""
    try:
        detail = fn() or ""
        report.add(CheckResult(name=name, passed=True, detail=detail))
    except Exception as exc:
        report.add(CheckResult(name=name, passed=False, error=str(exc)))


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

SCRATCH_TABLE = "_dm_feasibility_scratch"
SCRATCH_TABLE_CLOB = "_dm_feasibility_clob"
SCRATCH_TABLE_TRIGGER = "_dm_feasibility_trigger"


def _drop(conn, table: str) -> None:
    try:
        conn.execute(text(f"DROP TABLE {table}"))
    except Exception:
        pass


def _drop_trigger(conn, name: str) -> None:
    try:
        conn.execute(text(f"DROP TRIGGER {name}"))
    except Exception:
        pass


def check_connection(engine) -> str:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        assert result == 1
    return "Connected successfully; SELECT 1 returned 1"


def check_dialect_name(engine) -> str:
    name = engine.dialect.name
    assert name == "dm", f"Expected 'dm', got '{name}'"
    return f"Dialect name = '{name}'"


def check_clob_type(engine) -> str:
    with engine.begin() as conn:
        _drop(conn, SCRATCH_TABLE_CLOB)
        conn.execute(text(f"""
            CREATE TABLE {SCRATCH_TABLE_CLOB} (
                id   INT PRIMARY KEY,
                body CLOB
            )
        """))
        big = "x" * 100_000
        conn.execute(
            text(f"INSERT INTO {SCRATCH_TABLE_CLOB} VALUES (:id, :body)"),
            {"id": 1, "body": big},
        )
        row = conn.execute(text(f"SELECT body FROM {SCRATCH_TABLE_CLOB} WHERE id=1")).fetchone()
        assert row and len(row[0]) == 100_000
        _drop(conn, SCRATCH_TABLE_CLOB)
    return "CLOB column created; 100 000-char string round-tripped successfully"


def check_inspector_has_table(engine) -> str:
    with engine.begin() as conn:
        _drop(conn, SCRATCH_TABLE)
        conn.execute(text(f"CREATE TABLE {SCRATCH_TABLE} (id INT PRIMARY KEY)"))

    with engine.connect() as conn:
        insp = inspect(conn)
        assert insp.has_table(SCRATCH_TABLE), "has_table() returned False"
        assert not insp.has_table("_nonexistent_xyz_"), "has_table() should be False for missing table"

    with engine.begin() as conn:
        _drop(conn, SCRATCH_TABLE)
    return "inspect().has_table() works correctly"


def check_inspector_get_columns(engine) -> str:
    with engine.begin() as conn:
        _drop(conn, SCRATCH_TABLE)
        conn.execute(text(f"""
            CREATE TABLE {SCRATCH_TABLE} (
                id   INT PRIMARY KEY,
                name VARCHAR(100)
            )
        """))

    with engine.connect() as conn:
        cols = {c["name"].lower() for c in inspect(conn).get_columns(SCRATCH_TABLE)}
        assert "id" in cols and "name" in cols, f"Missing columns, got: {cols}"

    with engine.begin() as conn:
        _drop(conn, SCRATCH_TABLE)
    return f"inspect().get_columns() returned columns correctly"


def check_inspector_get_indexes(engine) -> str:
    with engine.begin() as conn:
        _drop(conn, SCRATCH_TABLE)
        conn.execute(text(f"CREATE TABLE {SCRATCH_TABLE} (id INT PRIMARY KEY, val INT)"))
        conn.execute(text(f"CREATE INDEX idx_feasibility_val ON {SCRATCH_TABLE}(val)"))

    with engine.connect() as conn:
        names = {i["name"].lower() for i in inspect(conn).get_indexes(SCRATCH_TABLE)}
        assert "idx_feasibility_val" in names, f"Index not found, got: {names}"

    with engine.begin() as conn:
        _drop(conn, SCRATCH_TABLE)
    return "inspect().get_indexes() found the created index"


def check_current_timestamp_default(engine) -> str:
    with engine.begin() as conn:
        _drop(conn, SCRATCH_TABLE)
        conn.execute(text(f"""
            CREATE TABLE {SCRATCH_TABLE} (
                id          INT PRIMARY KEY,
                create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text(f"INSERT INTO {SCRATCH_TABLE}(id) VALUES(1)"))
        row = conn.execute(text(f"SELECT create_time FROM {SCRATCH_TABLE} WHERE id=1")).fetchone()
        assert row and row[0] is not None, "create_time was NULL after insert"
        _drop(conn, SCRATCH_TABLE)
    return "TIMESTAMP DEFAULT CURRENT_TIMESTAMP populated correctly on INSERT"


def check_trigger_update_time(engine) -> str:
    """Verify BEFORE UPDATE trigger sets :new.update_time := CURRENT_TIMESTAMP."""
    import time

    with engine.begin() as conn:
        _drop_trigger(conn, f"trg_{SCRATCH_TABLE_TRIGGER}_update_time")
        _drop(conn, SCRATCH_TABLE_TRIGGER)
        conn.execute(text(f"""
            CREATE TABLE {SCRATCH_TABLE_TRIGGER} (
                id          INT PRIMARY KEY,
                val         VARCHAR(50),
                update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text(f"INSERT INTO {SCRATCH_TABLE_TRIGGER}(id, val) VALUES(1, 'a')"))

    # Create trigger using Oracle/DaMeng PL/SQL syntax
    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE OR REPLACE TRIGGER trg_{SCRATCH_TABLE_TRIGGER}_update_time
            BEFORE UPDATE ON {SCRATCH_TABLE_TRIGGER}
            FOR EACH ROW
            BEGIN
                :new.update_time := CURRENT_TIMESTAMP;
            END
        """))

    # Wait a moment, then update and check update_time changed
    time.sleep(1)
    with engine.begin() as conn:
        before = conn.execute(
            text(f"SELECT update_time FROM {SCRATCH_TABLE_TRIGGER} WHERE id=1")
        ).scalar()
        conn.execute(text(f"UPDATE {SCRATCH_TABLE_TRIGGER} SET val='b' WHERE id=1"))
        after = conn.execute(
            text(f"SELECT update_time FROM {SCRATCH_TABLE_TRIGGER} WHERE id=1")
        ).scalar()
        assert after != before, f"update_time did not change: before={before}, after={after}"

    with engine.begin() as conn:
        _drop_trigger(conn, f"trg_{SCRATCH_TABLE_TRIGGER}_update_time")
        _drop(conn, SCRATCH_TABLE_TRIGGER)

    return f"BEFORE UPDATE trigger with :new syntax updated update_time correctly"


def check_varchar255_alembic_version(engine) -> str:
    """Verify alembic_version-style table with VARCHAR(255) PK works."""
    tbl = "_dm_feasibility_alembic_version"
    with engine.begin() as conn:
        _drop(conn, tbl)
        conn.execute(text(f"""
            CREATE TABLE {tbl} (
                version_num VARCHAR(255) NOT NULL PRIMARY KEY
            )
        """))
        conn.execute(text(f"INSERT INTO {tbl} VALUES('abc123')"))
        row = conn.execute(text(f"SELECT version_num FROM {tbl}")).fetchone()
        assert row and row[0] == "abc123"
        _drop(conn, tbl)
    return "VARCHAR(255) PRIMARY KEY table created and inserted correctly"


def check_inspector_column_length(engine) -> str:
    """Verify inspect().get_columns() returns type length (needed for alembic_version width check)."""
    with engine.begin() as conn:
        _drop(conn, SCRATCH_TABLE)
        conn.execute(text(f"CREATE TABLE {SCRATCH_TABLE} (version_num VARCHAR(255) NOT NULL)"))

    with engine.connect() as conn:
        cols = inspect(conn).get_columns(SCRATCH_TABLE)
        col = next((c for c in cols if c["name"].lower() == "version_num"), None)
        assert col is not None, "version_num column not found"
        length = getattr(col["type"], "length", None)
        assert length == 255, f"Expected length=255, got {length}"

    with engine.begin() as conn:
        _drop(conn, SCRATCH_TABLE)
    return f"inspect().get_columns() returned type.length=255 correctly"


def check_sqlalchemy_orm_create_table(engine) -> str:
    """Verify SQLAlchemy can CREATE TABLE via ORM metadata (used by create_db_and_tables)."""
    from sqlalchemy import Column, Integer, String, MetaData, Table
    meta = MetaData()
    tbl = Table(
        "_dm_feasibility_orm",
        meta,
        Column("id", Integer, primary_key=True),
        Column("name", String(100)),
    )
    meta.create_all(engine)
    with engine.connect() as conn:
        assert inspect(conn).has_table("_dm_feasibility_orm")
    meta.drop_all(engine)
    return "SQLAlchemy ORM metadata.create_all() and drop_all() worked correctly"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="DaMeng feasibility check")
    parser.add_argument(
        "--url",
        default="dm+dmPython://SYSDBA:6o+%s3z2NK7J@192.168.107.9:5236/BISHENG",
        help="SQLAlchemy connection URL for DaMeng",
    )
    args = parser.parse_args()

    print(f"\nConnecting to: {args.url.split('@')[-1]}")  # hide credentials
    engine = sa.create_engine(args.url, echo=False)

    report = Report()

    check(report, "1. Basic connection (SELECT 1)", lambda: check_connection(engine))
    check(report, "2. Dialect name == 'dm'", lambda: check_dialect_name(engine))
    check(report, "3. CLOB type — large text round-trip (100k chars)", lambda: check_clob_type(engine))
    check(report, "4. Inspector.has_table() — table existence check", lambda: check_inspector_has_table(engine))
    check(report, "5. Inspector.get_columns() — column list", lambda: check_inspector_get_columns(engine))
    check(report, "6. Inspector.get_indexes() — index list", lambda: check_inspector_get_indexes(engine))
    check(report, "7. TIMESTAMP DEFAULT CURRENT_TIMESTAMP on INSERT", lambda: check_current_timestamp_default(engine))
    check(report, "8. BEFORE UPDATE trigger with :new syntax — update_time auto-set", lambda: check_trigger_update_time(engine))
    check(report, "9. VARCHAR(255) PRIMARY KEY (alembic_version table)", lambda: check_varchar255_alembic_version(engine))
    check(report, "10. Inspector.get_columns() returns type.length", lambda: check_inspector_column_length(engine))
    check(report, "11. SQLAlchemy ORM metadata.create_all() / drop_all()", lambda: check_sqlalchemy_orm_create_table(engine))

    report.print()


if __name__ == "__main__":
    main()
