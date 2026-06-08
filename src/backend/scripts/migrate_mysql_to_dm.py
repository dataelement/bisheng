#!/usr/bin/env python3
"""Unified MySQL -> DaMeng (DM8) DATA migration for BiSheng / Gateway / OpenFGA.

Scope
-----
This script ONLY copies row data from MySQL to DM. It does NOT create tables.
The target DM schema (tables / triggers / indexes / migration-version tables)
must already exist, created by each application's own authoritative path:

  * bisheng         : start the backend once against DM
                      (SQLModel.metadata.create_all + startup triggers), or run
                      `alembic upgrade head` against the DM URL.
  * bisheng_gateway : execute docker/db/init_dm.sql on the DM schema.
  * openfga         : run `openfga migrate --datastore-engine dm --datastore-uri ...`.

For each logical database the script:
  1. reflects the TARGET DM tables (authoritative table list);
  2. for every target table reads the same-named MySQL table;
  3. converts values per target column type (JSON/CLOB, bool, bytes, ...);
  4. inserts in batches with IDENTITY_INSERT enabled and triggers/FKs disabled;
  5. re-enables triggers + FK constraints and reseeds IDENTITY counters.

Run it inside the bisheng backend venv so the DM dialect monkey-patches in
`bisheng.core.database.dialect_helpers` are loaded:

    cd src/backend
    uv run python ../../scripts/migrate_mysql_to_dm.py --config migrate_dm.yaml

Config file (YAML) example -> see scripts/migrate_dm.example.yaml
Every connection value may also be supplied / overridden via env vars.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

import sqlalchemy as sa
from sqlalchemy import MetaData, Table, inspect, text
from sqlalchemy.engine import Engine

# Importing this module installs the DM dialect patches (BOOLEAN->SMALLINT,
# LONGTEXT/JSON->CLOB, CHAR handling, IDENTITY autoincrement fix). It is a
# no-op on platforms without dmSQLAlchemy installed.
try:
    import bisheng.core.database.dialect_helpers  # noqa: F401
except Exception:  # pragma: no cover - script may run outside bisheng venv
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mysql2dm")


# ---------------------------------------------------------------------------
# Configuration model
# ---------------------------------------------------------------------------
@dataclass
class DbJob:
    name: str
    source_url: str                       # mysql+pymysql://user:pass@host:port/db
    target_url: str                       # dm+dmPython://user:pass@host:port/SCHEMA
    include: list[str] = field(default_factory=list)   # empty = all reflected tables
    exclude: list[str] = field(default_factory=list)


def _expand_env(value: str) -> str:
    """Allow ${VAR} / ${VAR:-default} placeholders inside config strings."""
    return os.path.expandvars(value) if value else value


def load_jobs(config_path: str) -> list[DbJob]:
    import yaml  # local import: only needed when a config file is used

    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    jobs: list[DbJob] = []
    for name, cfg in (raw.get("databases") or {}).items():
        jobs.append(
            DbJob(
                name=name,
                source_url=_expand_env(cfg["source_url"]),
                target_url=_expand_env(cfg["target_url"]),
                include=cfg.get("include") or [],
                exclude=cfg.get("exclude") or [],
            )
        )
    if not jobs:
        raise SystemExit("No `databases:` entries found in config file.")
    return jobs


# ---------------------------------------------------------------------------
# DaMeng catalog helpers
#
# SQLAlchemy's inspector returns table names in lowercase, but DM stores
# unquoted identifiers UPPERCASE and quoted reserved words (group/user) in their
# original case. Raw DDL/DML (SET IDENTITY_INSERT, ALTER TRIGGER, ALTER TABLE
# ... CONSTRAINT) must use the *actual* catalog name. We build a lower->actual
# map from SYS.ALL_TABLES once per job.
# ---------------------------------------------------------------------------
def dm_actual_table_map(conn) -> dict[str, str]:
    rows = conn.execute(
        text("SELECT TABLE_NAME FROM SYS.ALL_TABLES WHERE OWNER = USER")
    )
    return {r[0].lower(): r[0] for r in rows}


def dm_quote(actual_name: str) -> str:
    """Quote a DM identifier only when it is not already all-uppercase."""
    return actual_name if actual_name == actual_name.upper() else f'"{actual_name}"'


def dm_triggers_for(conn, actual_table: str) -> list[str]:
    rows = conn.execute(
        text(
            "SELECT TRIGGER_NAME FROM USER_TRIGGERS "
            "WHERE TABLE_NAME = :t"
        ),
        {"t": actual_table},
    )
    return [r[0] for r in rows]


def dm_fk_constraints(conn) -> list[tuple[str, str]]:
    """Return (table_name, constraint_name) for every foreign key in the schema."""
    rows = conn.execute(
        text(
            "SELECT TABLE_NAME, CONSTRAINT_NAME FROM USER_CONSTRAINTS "
            "WHERE CONSTRAINT_TYPE = 'R'"
        )
    )
    return [(r[0], r[1]) for r in rows]


def dm_identity_column(conn, actual_table: str) -> str | None:
    """Return the IDENTITY column name of a DM table, or None."""
    rows = conn.execute(
        text(
            "SELECT COLUMN_NAME FROM ALL_TAB_COLUMNS "
            "WHERE TABLE_NAME = :t AND OWNER = USER AND IDENTITY = 'YES'"
        ),
        {"t": actual_table},
    )
    row = rows.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Value conversion: MySQL row value -> DM-acceptable bind value
# ---------------------------------------------------------------------------
def convert_value(value: Any, target_type: Any) -> Any:
    if value is None:
        return None

    type_name = type(target_type).__name__.upper()

    # JSON / dict / list -> CLOB text. MySQL native JSON columns are reflected
    # by SQLAlchemy as dict/list; DM stores them as serialized CLOB.
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)

    # CLOB/TEXT targets: ensure str. bytes -> utf-8 decoded text.
    if "CLOB" in type_name or "TEXT" in type_name or "VARCHAR" in type_name or "CHAR" in type_name:
        if isinstance(value, (bytes, bytearray)):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return value.decode("utf-8", "replace")
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return value

    # Decimal passthrough (DM handles), datetime/date passthrough.
    if isinstance(value, (Decimal, _dt.datetime, _dt.date, _dt.time)):
        return value

    return value


# ---------------------------------------------------------------------------
# Per-table copy
# ---------------------------------------------------------------------------
def copy_table(
    src_engine: Engine,
    dst_engine: Engine,
    table_name: str,
    actual_name: str,
    batch_size: int,
    truncate: bool,
    dry_run: bool,
) -> int:
    # Reflect both sides for the same table name.
    src_md = MetaData()
    dst_md = MetaData()
    try:
        src_tbl = Table(table_name, src_md, autoload_with=src_engine)
    except Exception as exc:
        log.warning("  [skip] source table %s not found: %s", table_name, exc)
        return 0
    dst_tbl = Table(table_name, dst_md, autoload_with=dst_engine)

    # Only copy columns present on BOTH sides (defensive against drift).
    common_cols = [c.name for c in dst_tbl.columns if c.name in src_tbl.columns]
    dst_col_types = {c.name: c.type for c in dst_tbl.columns}

    total = 0
    quoted = dm_quote(actual_name)

    with src_engine.connect() as s_conn:
        row_count = s_conn.execute(
            sa.select(sa.func.count()).select_from(src_tbl)
        ).scalar_one()
        if row_count == 0:
            log.info("  %-32s 0 rows (empty)", table_name)
            return 0

        if dry_run:
            log.info("  %-32s %d rows (dry-run, not written)", table_name, row_count)
            return row_count

        identity_col = None
        with dst_engine.begin() as d_conn:
            identity_col = dm_identity_column(d_conn, actual_name)
            if truncate:
                d_conn.execute(text(f"DELETE FROM {quoted}"))
            if identity_col:
                d_conn.execute(text(f"SET IDENTITY_INSERT {quoted} ON"))

            insert_stmt = dst_tbl.insert()
            select_stmt = sa.select(*[src_tbl.c[c] for c in common_cols])
            result = s_conn.execution_options(stream_results=True).execute(select_stmt)

            batch: list[dict] = []
            for row in result:
                mapping = dict(row._mapping)
                converted = {
                    col: convert_value(mapping[col], dst_col_types[col])
                    for col in common_cols
                }
                batch.append(converted)
                if len(batch) >= batch_size:
                    d_conn.execute(insert_stmt, batch)
                    total += len(batch)
                    batch.clear()
                    log.info("  %-32s %d/%d", table_name, total, row_count)
            if batch:
                d_conn.execute(insert_stmt, batch)
                total += len(batch)

            if identity_col:
                d_conn.execute(text(f"SET IDENTITY_INSERT {quoted} OFF"))

    if identity_col:
        reseed_identity(dst_engine, quoted, identity_col)

    log.info("  %-32s done: %d rows", table_name, total)
    return total


def reseed_identity(dst_engine: Engine, quoted_table: str, id_col: str) -> None:
    """Advance the IDENTITY high-water mark past the largest copied id.

    After IDENTITY_INSERT the generator is not advanced automatically, so the
    next auto-generated id would collide. DM lets us reset the seed via
    ALTER TABLE ... MODIFY <col> IDENTITY(next, 1).
    """
    try:
        with dst_engine.begin() as conn:
            max_id = conn.execute(
                text(f"SELECT COALESCE(MAX({id_col}), 0) FROM {quoted_table}")
            ).scalar_one()
            next_id = int(max_id) + 1
            conn.execute(
                text(
                    f"ALTER TABLE {quoted_table} "
                    f"MODIFY {id_col} IDENTITY({next_id}, 1)"
                )
            )
        log.info("  reseed identity %s.%s -> %d", quoted_table, id_col, next_id)
    except Exception as exc:
        log.warning(
            "  could not reseed identity for %s.%s (%s); "
            "reseed manually if next insert collides", quoted_table, id_col, exc
        )


# ---------------------------------------------------------------------------
# Per-database job
# ---------------------------------------------------------------------------
def resolve_tables(dst_engine: Engine, job: DbJob) -> list[str]:
    names = inspect(dst_engine).get_table_names()
    if job.include:
        wanted = [t for t in job.include if t in names]
        missing = set(job.include) - set(names)
        if missing:
            log.warning("[%s] include tables not present on DM: %s", job.name, missing)
    else:
        wanted = names
    # Migration-version bookkeeping tables are owned by each app's own migration
    # tool on the DM side (alembic upgrade / openfga migrate), never copied.
    skip = set(job.exclude) | {"alembic_version", "goose_db_version"}
    # Sort for a stable, reproducible order (required by --resume-from). FK
    # constraints are disabled during load, so insertion order is irrelevant.
    return sorted(t for t in wanted if t not in skip)


def run_job(
    job: DbJob,
    batch_size: int,
    truncate: bool,
    dry_run: bool,
    resume_from: str | None = None,
) -> None:
    log.info("=" * 70)
    log.info("DATABASE: %s", job.name)
    log.info("  source: %s", _mask(job.source_url))
    log.info("  target: %s", _mask(job.target_url))

    src_engine = sa.create_engine(job.source_url, pool_pre_ping=True)
    # DM sync engine: strip the schema path (dmPython.connect has no `database` kwarg)
    target_url = _dm_strip_path(job.target_url)
    dst_engine = sa.create_engine(target_url, pool_pre_ping=True)

    tables = resolve_tables(dst_engine, job)
    # Resume support: skip every table before `resume_from` (use after a failure).
    if resume_from:
        if resume_from in tables:
            idx = tables.index(resume_from)
            log.info("  resuming from '%s' (skipping %d earlier tables)", resume_from, idx)
            tables = tables[idx:]
        else:
            log.warning("  --resume-from '%s' not found; starting from the beginning", resume_from)
    log.info("  %d tables to migrate", len(tables))

    # Build the DM actual-name map and pre-disable all FK constraints + triggers
    # so we can load tables in any order and preserve original timestamps.
    disabled_fks: list[tuple[str, str]] = []
    disabled_triggers: list[str] = []
    with dst_engine.connect() as conn:
        actual_map = dm_actual_table_map(conn)

    if not dry_run:
        with dst_engine.begin() as conn:
            for tname, cname in dm_fk_constraints(conn):
                conn.execute(
                    text(f"ALTER TABLE {dm_quote(tname)} DISABLE CONSTRAINT {cname}")
                )
                disabled_fks.append((tname, cname))
            for t in tables:
                actual = actual_map.get(t, t.upper())
                for trg in dm_triggers_for(conn, actual):
                    conn.execute(text(f"ALTER TRIGGER {trg} DISABLE"))
                    disabled_triggers.append(trg)
        log.info("  disabled %d FK(s), %d trigger(s)", len(disabled_fks), len(disabled_triggers))

    grand_total = 0
    try:
        for t in tables:
            actual = actual_map.get(t, t.upper())
            grand_total += copy_table(
                src_engine, dst_engine, t, actual, batch_size, truncate, dry_run
            )
    finally:
        if not dry_run:
            with dst_engine.begin() as conn:
                for trg in disabled_triggers:
                    _safe(conn, f"ALTER TRIGGER {trg} ENABLE")
                for tname, cname in disabled_fks:
                    # ENABLE NOVALIDATE: trust copied data, skip full re-check.
                    _safe(conn, f"ALTER TABLE {dm_quote(tname)} ENABLE NOVALIDATE CONSTRAINT {cname}")
            log.info("  re-enabled triggers and FK constraints")

    log.info("DATABASE %s complete: %d rows total", job.name, grand_total)


def verify_job(job: DbJob) -> bool:
    """Compare per-table row counts between MySQL source and DM target.

    Returns True when every migrated table matches, False otherwise.
    """
    log.info("=" * 70)
    log.info("VERIFY: %s", job.name)
    log.info("  source: %s", _mask(job.source_url))
    log.info("  target: %s", _mask(job.target_url))

    src_engine = sa.create_engine(job.source_url, pool_pre_ping=True)
    dst_engine = sa.create_engine(_dm_strip_path(job.target_url), pool_pre_ping=True)

    tables = resolve_tables(dst_engine, job)
    ok = True
    with src_engine.connect() as s_conn, dst_engine.connect() as d_conn:
        actual_map = dm_actual_table_map(d_conn)
        for t in tables:
            quoted = dm_quote(actual_map.get(t, t.upper()))
            dst_n = d_conn.execute(text(f"SELECT COUNT(*) FROM {quoted}")).scalar_one()
            try:
                src_n = s_conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar_one()
            except Exception as exc:
                log.warning("  %-32s source missing: %s", t, exc)
                ok = False
                continue
            if src_n == dst_n:
                log.info("  %-32s OK     mysql=%d dm=%d", t, src_n, dst_n)
            else:
                log.error("  %-32s MISMATCH mysql=%d dm=%d (diff=%d)",
                          t, src_n, dst_n, src_n - dst_n)
                ok = False

    log.info("VERIFY %s: %s", job.name, "PASS" if ok else "FAIL")
    return ok


def _safe(conn, statement: str) -> None:
    try:
        conn.execute(text(statement))
    except Exception as exc:
        log.warning("  statement failed (continuing): %s -> %s", statement, exc)


def _dm_strip_path(url: str) -> str:
    """Strip /SCHEMA from a dm+dmPython sync URL (see bisheng connection.py)."""
    if "dm+dmPython" not in url:
        return url
    at = url.find("@")
    if at == -1:
        return url
    after = url[at + 1:]
    slash = after.find("/")
    if slash == -1:
        return url
    return url[: at + 1 + slash]


def _mask(url: str) -> str:
    """Hide the password when logging a DSN."""
    import re

    return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1***\2", url)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MySQL -> DaMeng data migration")
    parser.add_argument("--config", required=True, help="YAML config path")
    parser.add_argument("--db", action="append", default=[],
                        help="Only migrate these database names (repeatable). Default: all.")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--truncate", action="store_true",
                        help="DELETE FROM each target table before loading (idempotent re-runs).")
    parser.add_argument("--resume-from", metavar="TABLE", default=None,
                        help="Skip tables before TABLE in the sorted list (use after a mid-run failure). "
                             "Only valid with a single --db.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Connect, reflect and count rows but write nothing.")
    parser.add_argument("--verify", action="store_true",
                        help="Verification only: compare per-table row counts "
                             "between MySQL and DM, copy nothing.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    jobs = load_jobs(args.config)
    if args.db:
        jobs = [j for j in jobs if j.name in args.db]
        if not jobs:
            log.error("No matching database for --db %s", args.db)
            return 2

    if args.verify:
        all_ok = True
        for job in jobs:
            try:
                all_ok = verify_job(job) and all_ok
            except Exception:
                log.exception("Verify FAILED to run for database %s", job.name)
                all_ok = False
        log.info("Verification %s.", "PASSED" if all_ok else "FAILED")
        return 0 if all_ok else 1

    if args.resume_from and len(jobs) > 1:
        log.error("--resume-from requires a single --db (got %d databases).", len(jobs))
        return 2

    for job in jobs:
        try:
            run_job(job, args.batch_size, args.truncate, args.dry_run, args.resume_from)
        except Exception:
            log.exception("Migration FAILED for database %s", job.name)
            return 1
    log.info("All migrations finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
