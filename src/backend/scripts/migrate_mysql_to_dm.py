#!/usr/bin/env python3
"""Unified MySQL -> DaMeng (DM8) DATA migration for BiSheng / Gateway / OpenFGA.

Scope
-----
By default this script ONLY copies row data from MySQL to DM; the target DM
schema must already exist, created by each application's own authoritative path:

  * bisheng         : start the backend once against DM
                      (SQLModel.metadata.create_all + startup triggers), or run
                      `alembic upgrade head` against the DM URL.
  * bisheng_gateway : execute docker/db/init_dm.sql on the DM schema.
  * openfga         : run `openfga migrate --datastore-engine dm --datastore-uri ...`.

Pass --create-schema to instead create the DM tables generically from the MySQL
schema (reflect + create_all, idempotent). This is uniform across all three
databases and needs no app-specific tooling, but it does NOT create bisheng's
update_time/computed-column triggers (added by the bisheng app at first startup)
nor the DM user/schema itself (a DBA step).

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
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

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


def _patch_dm_skip_index_reflection() -> None:
    """Skip DM index reflection during this migration (data-copy only).

    dmSQLAlchemy's ``_get_indexes_rows`` mutates ``BaseRow._data`` in place
    (``col_dict._data = col_dict._data + (...)``). That attribute is read-only
    when SQLAlchemy's C extension is installed, so reflecting any DM table that
    has indexes raises::

        AttributeError: attribute '_data' of '...BaseRow' objects is not writable

    The migration only reflects the target table's column names/types to build
    the INSERT — it never needs index metadata. Stub ``_get_indexes_rows`` to an
    empty result so ``Table(..., autoload_with=dm_engine)`` skips the broken code
    path. Scoped to this script on purpose: doing it globally in dialect_helpers
    would make alembic's ``index_exists`` guards always report "no index" and
    wrongly re-create indexes.
    """
    try:
        from dmSQLAlchemy.base import DMDialect  # type: ignore[import]
    except ImportError:
        return  # not on a DaMeng-capable platform

    def _no_index_rows(self, *args, **kwargs):
        return []

    DMDialect._get_indexes_rows = _no_index_rows


_patch_dm_skip_index_reflection()

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
    source_url: str  # mysql+pymysql://user:pass@host:port/db
    target_url: str  # dm+dmPython://user:pass@host:port/?schema=SCHEMA
    include: list[str] = field(default_factory=list)  # empty = all reflected tables
    exclude: list[str] = field(default_factory=list)


_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _expand_env(value: str) -> str:
    """Expand ${VAR}, $VAR and ${VAR:-default} placeholders inside config strings.

    Unlike os.path.expandvars (which silently leaves ${VAR:-default} literal and
    has no default support at all), this honors the bash-style ":-default"
    fallback so the documented defaults in migrate_dm.example.yaml work whether
    or not the shell wrapper exported the variable.
    """
    if not value:
        return value

    def _sub(m: re.Match[str]) -> str:
        braced_name, default, bare_name = m.group(1), m.group(2), m.group(3)
        name = braced_name or bare_name
        env_val = os.environ.get(name)
        if env_val is not None and env_val != "":
            return env_val
        if default is not None:
            return default
        # Unset and no default: leave the original placeholder so the failure is
        # visible (e.g. an invalid DSN) rather than silently blank.
        return m.group(0)

    return _ENV_PLACEHOLDER.sub(_sub, value)


def load_jobs(config_path: str) -> list[DbJob]:
    import yaml  # local import: only needed when a config file is used

    with open(config_path, encoding="utf-8") as fh:
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
def dm_actual_table_map(conn, schema: str | None = None) -> dict[str, str]:
    """Map lowercase -> actual catalog table name for the target schema.

    schema=None keeps the original behavior (the login user's own schema, via
    OWNER = USER). When a schema is given (one-account / multiple-schema DM
    deployment), scope to OWNER = :owner so each job sees only its schema's tables.
    """
    if schema is None:
        rows = conn.execute(text("SELECT TABLE_NAME FROM SYS.ALL_TABLES WHERE OWNER = USER"))
    else:
        rows = conn.execute(text("SELECT TABLE_NAME FROM SYS.ALL_TABLES WHERE OWNER = :owner"), {"owner": schema})
    return {r[0].lower(): r[0] for r in rows}


def dm_quote(actual_name: str) -> str:
    """Quote a DM identifier only when it is not already all-uppercase."""
    return actual_name if actual_name == actual_name.upper() else f'"{actual_name}"'


def dm_qualify(schema: str | None, actual_name: str) -> str:
    """Return a (optionally schema-qualified) quoted DM identifier.

    schema=None -> "TABLE"; schema set -> "SCHEMA"."TABLE", so raw DDL/DML lands
    in the right schema even though the connection logs in as a different user.
    """
    quoted = dm_quote(actual_name)
    return quoted if schema is None else f"{dm_quote(schema)}.{quoted}"


def dm_triggers_for(conn, actual_table: str, schema: str | None = None) -> list[str]:
    if schema is None:
        rows = conn.execute(
            text("SELECT TRIGGER_NAME FROM USER_TRIGGERS WHERE TABLE_NAME = :t"),
            {"t": actual_table},
        )
    else:
        rows = conn.execute(
            text("SELECT TRIGGER_NAME FROM SYS.ALL_TRIGGERS WHERE TABLE_OWNER = :owner AND TABLE_NAME = :t"),
            {"owner": schema, "t": actual_table},
        )
    return [r[0] for r in rows]


def dm_fk_constraints(conn, schema: str | None = None) -> list[tuple[str, str]]:
    """Return (table_name, constraint_name) for every foreign key in the schema."""
    if schema is None:
        rows = conn.execute(
            text("SELECT TABLE_NAME, CONSTRAINT_NAME FROM USER_CONSTRAINTS WHERE CONSTRAINT_TYPE = 'R'")
        )
    else:
        rows = conn.execute(
            text(
                "SELECT TABLE_NAME, CONSTRAINT_NAME FROM SYS.ALL_CONSTRAINTS WHERE OWNER = :owner AND CONSTRAINT_TYPE = 'R'"
            ),
            {"owner": schema},
        )
    return [(r[0], r[1]) for r in rows]


def reflected_identity_col(dst_tbl: Table) -> str | None:
    """Return the IDENTITY/autoincrement column of an already-reflected DM table.

    Read from the reflection we already did rather than a hand-written catalog
    query: dmSQLAlchemy marks identity columns during reflection (autoincrement /
    Identity), whereas DM's ALL_TAB_COLUMNS exposes no portable IDENTITY flag
    column on this build (neither IDENTITY nor IDENTITY_COLUMN exists). Returns
    the first identity column name, or None.
    """
    for c in dst_tbl.columns:
        # autoincrement defaults to 'auto' for unflagged columns, so only an
        # explicit True (set by the dialect for a real identity column) counts.
        if c.identity is not None or c.autoincrement is True:
            return c.name
    return None


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
    schema: str | None = None,
) -> int:
    # Reflect both sides for the same table name. The DM side is reflected within
    # `schema` (None = the login user's own schema) so a one-account/multi-schema
    # deployment targets the right schema instead of the login user's default.
    src_md = MetaData()
    dst_md = MetaData()
    try:
        src_tbl = Table(table_name, src_md, autoload_with=src_engine)
    except Exception as exc:
        log.warning("  [skip] source table %s not found: %s", table_name, exc)
        return 0
    dst_tbl = Table(table_name, dst_md, schema=schema, autoload_with=dst_engine)

    # Only copy columns present on BOTH sides (defensive against drift).
    common_cols = [c.name for c in dst_tbl.columns if c.name in src_tbl.columns]
    dst_col_types = {c.name: c.type for c in dst_tbl.columns}

    total = 0
    quoted = dm_qualify(schema, actual_name)

    with src_engine.connect() as s_conn:
        row_count = s_conn.execute(sa.select(sa.func.count()).select_from(src_tbl)).scalar_one()

        if dry_run:
            log.info("  %-32s %d rows (dry-run, not written)", table_name, row_count)
            return row_count

        if row_count == 0:
            # Even with an empty source, --truncate must still clear the target so a
            # table emptied upstream (or pre-seeded by an init script) ends up
            # matching the source — otherwise stale rows survive and break the
            # idempotency that --truncate promises.
            if truncate:
                with dst_engine.begin() as d_conn:
                    d_conn.execute(text(f"DELETE FROM {quoted}"))
                log.info("  %-32s 0 rows (source empty; target truncated)", table_name)
            else:
                log.info("  %-32s 0 rows (empty)", table_name)
            return 0

        identity_col = reflected_identity_col(dst_tbl)
        with dst_engine.begin() as d_conn:
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
                converted = {col: convert_value(mapping[col], dst_col_types[col]) for col in common_cols}
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
    next auto-generated id would collide. DM rejects re-declaring IDENTITY on an
    already-identity column (`MODIFY <col> IDENTITY(n,1)` -> "already contains
    identity column"), and the correct reset clause varies across DM builds, so
    we try the known forms in order and keep the first that the server accepts.
    Each attempt runs in its own transaction so a rejected one does not poison the
    next. A total failure is non-fatal (data is already copied) — it only means
    the next app insert may need a manual reseed.
    """
    try:
        with dst_engine.connect() as conn:
            max_id = conn.execute(text(f"SELECT COALESCE(MAX({id_col}), 0) FROM {quoted_table}")).scalar_one()
        next_id = int(max_id) + 1
    except Exception as exc:
        log.warning("  could not read MAX(%s) on %s for reseed (%s)", id_col, quoted_table, exc)
        return

    candidates = (
        f"ALTER TABLE {quoted_table} ALTER COLUMN {id_col} RESTART WITH {next_id}",
        f"ALTER TABLE {quoted_table} MODIFY {id_col} GENERATED BY DEFAULT AS IDENTITY (START WITH {next_id})",
        f"ALTER TABLE {quoted_table} MODIFY {id_col} IDENTITY({next_id}, 1)",
    )
    last_exc: Exception | None = None
    for stmt in candidates:
        try:
            with dst_engine.begin() as conn:
                conn.execute(text(stmt))
            log.info("  reseed identity %s.%s -> %d", quoted_table, id_col, next_id)
            return
        except Exception as exc:
            last_exc = exc
    log.warning(
        "  could not reseed identity for %s.%s (%s); reseed manually if next insert collides",
        quoted_table,
        id_col,
        last_exc,
    )


# ---------------------------------------------------------------------------
# Schema auto-creation (optional, --create-schema)
#
# One uniform mechanism for all three databases: reflect each MySQL source
# table and let create_all() emit the CREATE TABLE on DM. The dialect_helpers
# patches map most types (BOOLEAN->SMALLINT, LONGTEXT/JSON->CLOB, CHAR->VARCHAR,
# autoincrement->IDENTITY); _normalize_reflected_for_dm handles the remaining
# MySQL-only types/defaults that those patches do not cover.
# ---------------------------------------------------------------------------
def _normalize_reflected_for_dm(md: MetaData) -> None:
    """Adjust reflected MySQL types/defaults so create_all emits valid DM DDL."""
    from sqlalchemy import CLOB, Integer, String
    from sqlalchemy.dialects import mysql

    big_text = (mysql.LONGTEXT, mysql.MEDIUMTEXT, mysql.TINYTEXT, mysql.TEXT, mysql.JSON)
    small_int = (mysql.MEDIUMINT, mysql.YEAR)

    for tbl in md.tables.values():
        for col in tbl.columns:
            t = col.type
            # DM has no UNSIGNED / ZEROFILL.
            if getattr(t, "unsigned", False):
                t.unsigned = False
            if getattr(t, "zerofill", False):
                t.zerofill = False
            # MySQL collation/charset names are not valid on DM.
            if getattr(t, "collation", None):
                t.collation = None
            if hasattr(t, "charset"):
                t.charset = None

            # MySQL-only large text / JSON -> CLOB.
            if isinstance(t, big_text):
                col.type = CLOB()
            # ENUM / SET have no DM equivalent -> VARCHAR sized to the values.
            elif isinstance(t, (mysql.ENUM, mysql.SET)):
                values = list(getattr(t, "enums", []) or [])
                if isinstance(t, mysql.SET):
                    width = sum(len(v) + 1 for v in values) or 255
                else:
                    width = max((len(v) for v in values), default=64)
                col.type = String(width)
            # MEDIUMINT / YEAR -> INTEGER.
            elif isinstance(t, small_int):
                col.type = Integer()

            # Strip "ON UPDATE CURRENT_TIMESTAMP" from server defaults: invalid in
            # a DM column default. On DM the bisheng app maintains update_time via
            # a startup trigger instead.
            sd = col.server_default
            if sd is not None and getattr(sd, "arg", None) is not None:
                txt = str(sd.arg)
                if "ON UPDATE" in txt.upper():
                    head = re.split(r"(?i)\bON UPDATE\b", txt)[0].strip()
                    col.server_default = sa.DefaultClause(sa.text(head)) if head else None


def create_schema(src_engine: Engine, dst_engine: Engine, job: DbJob) -> None:
    """Reflect the MySQL source schema and create matching tables on DM.

    Idempotent: existing DM tables are left untouched (checkfirst=True).

    Not created here: bisheng's update_time / computed-column triggers — the
    bisheng app installs those at first startup against DM. The target DM
    user/schema itself must already exist (a DBA step); this only creates tables,
    indexes and constraints inside it.
    """
    insp = inspect(src_engine)
    names = insp.get_table_names()
    skip = set(job.exclude) | {"alembic_version", "goose_db_version"}
    if job.include:
        names = [t for t in names if t in job.include]
    names = sorted(t for t in names if t not in skip)
    if not names:
        log.warning("  schema: no source tables to create")
        return

    md = MetaData()
    md.reflect(bind=src_engine, only=names)
    _normalize_reflected_for_dm(md)

    existing = set(inspect(dst_engine).get_table_names())
    to_create = [t for t in names if t not in existing]
    log.info(
        "  schema: %d source table(s), %d already on DM, creating %d",
        len(names),
        len(names) - len(to_create),
        len(to_create),
    )
    # create_all sorts by FK dependency and skips existing tables (checkfirst).
    md.create_all(bind=dst_engine, checkfirst=True)
    log.info("  schema: creation done")


# ---------------------------------------------------------------------------
# Per-database job
# ---------------------------------------------------------------------------
def resolve_tables(src_engine: Engine, dst_engine: Engine, job: DbJob, schema: str | None = None) -> list[str]:
    names = inspect(dst_engine).get_table_names(schema=schema)
    # Source MySQL connection is scoped to this job's database (the URL's /dbname),
    # so its table list is exactly this logical database's tables. Used below to
    # keep each job to its own tables even when several logical databases were
    # consolidated into a SINGLE DM account/schema — in that case reflecting the
    # DM target returns the UNION of every database's tables, and without this
    # scoping the bisheng_gateway job would also try to copy bisheng/openfga
    # tables (and could overwrite same-named DM tables with the wrong source).
    src_names = {t.lower() for t in inspect(src_engine).get_table_names()}

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

    candidates = [t for t in wanted if t not in skip]
    resolved = [t for t in candidates if t.lower() in src_names]
    # Tables present on the DM target but absent from this job's source DB belong
    # to another logical database sharing the same DM schema — drop them quietly
    # (info, not warning) so the log isn't flooded with per-table "[skip]" lines.
    foreign = [t for t in candidates if t.lower() not in src_names]
    if foreign:
        log.info(
            "  %d DM table(s) not in source '%s' (other DB in a shared schema) — skipped",
            len(foreign),
            job.name,
        )
    # Sort for a stable, reproducible order (required by --resume-from). FK
    # constraints are disabled during load, so insertion order is irrelevant.
    return sorted(resolved)


def run_job(
    job: DbJob,
    batch_size: int,
    truncate: bool,
    dry_run: bool,
    resume_from: str | None = None,
    create_schema_first: bool = False,
) -> None:
    log.info("=" * 70)
    log.info("DATABASE: %s", job.name)
    log.info("  source: %s", _mask(job.source_url))
    log.info("  target: %s", _mask(job.target_url))

    src_engine = sa.create_engine(job.source_url, pool_pre_ping=True)
    # DM engine: carry the schema via ?schema= (dmPython.connect has no `database`
    # kwarg). The schema is ALSO applied explicitly (OWNER=:schema / "SCHEMA"."T")
    # so a one-account/multi-schema DM deployment targets the right schema even
    # when the login user differs from the schema.
    target_url = _dm_connect_url(job.target_url)
    dst_engine = sa.create_engine(target_url, pool_pre_ping=True)

    schema = _dm_schema_from_url(job.target_url)
    if schema is not None:
        with dst_engine.connect() as conn:
            schema = resolve_dm_schema(conn, schema)
        log.info("  schema: %s (qualifying all reflection/DML to this DM schema)", schema)

    # Optionally create the DM tables from the MySQL schema before loading data.
    if create_schema_first:
        if schema is not None:
            # create_schema reflects/creates in the login user's own schema, not a
            # named one. With a ?schema= target that would build tables in the wrong
            # place — refuse and let the app's own tooling create the schema.
            raise SystemExit(
                f"--create-schema is not supported with a ?schema= target ('{schema}'). "
                "Pre-create the schema via the app's own path (alembic / init_dm.sql / "
                "openfga migrate), then re-run without --create-schema."
            )
        if dry_run:
            log.info("  (dry-run) would create schema from MySQL reflection")
        else:
            create_schema(src_engine, dst_engine, job)

    tables = resolve_tables(src_engine, dst_engine, job, schema)
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
        actual_map = dm_actual_table_map(conn, schema)

    if not dry_run:
        with dst_engine.begin() as conn:
            for tname, cname in dm_fk_constraints(conn, schema):
                conn.execute(text(f"ALTER TABLE {dm_qualify(schema, tname)} DISABLE CONSTRAINT {cname}"))
                disabled_fks.append((tname, cname))
            for t in tables:
                actual = actual_map.get(t, t.upper())
                for trg in dm_triggers_for(conn, actual, schema):
                    conn.execute(text(f"ALTER TRIGGER {dm_qualify(schema, trg)} DISABLE"))
                    disabled_triggers.append(trg)
        log.info("  disabled %d FK(s), %d trigger(s)", len(disabled_fks), len(disabled_triggers))

    grand_total = 0
    try:
        for t in tables:
            actual = actual_map.get(t, t.upper())
            grand_total += copy_table(src_engine, dst_engine, t, actual, batch_size, truncate, dry_run, schema)
    finally:
        if not dry_run:
            with dst_engine.begin() as conn:
                for trg in disabled_triggers:
                    _safe(conn, f"ALTER TRIGGER {dm_qualify(schema, trg)} ENABLE")
                for tname, cname in disabled_fks:
                    # ENABLE NOVALIDATE: trust copied data, skip full re-check.
                    _safe(conn, f"ALTER TABLE {dm_qualify(schema, tname)} ENABLE NOVALIDATE CONSTRAINT {cname}")
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
    dst_engine = sa.create_engine(_dm_connect_url(job.target_url), pool_pre_ping=True)

    schema = _dm_schema_from_url(job.target_url)
    if schema is not None:
        with dst_engine.connect() as conn:
            schema = resolve_dm_schema(conn, schema)

    tables = resolve_tables(src_engine, dst_engine, job, schema)
    ok = True
    with src_engine.connect() as s_conn, dst_engine.connect() as d_conn:
        actual_map = dm_actual_table_map(d_conn, schema)
        for t in tables:
            quoted = dm_qualify(schema, actual_map.get(t, t.upper()))
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
                log.error("  %-32s MISMATCH mysql=%d dm=%d (diff=%d)", t, src_n, dst_n, src_n - dst_n)
                ok = False

    log.info("VERIFY %s: %s", job.name, "PASS" if ok else "FAIL")
    return ok


def _safe(conn, statement: str) -> None:
    try:
        conn.execute(text(statement))
    except Exception as exc:
        log.warning("  statement failed (continuing): %s -> %s", statement, exc)


def _dm_schema_from_url(url: str) -> str | None:
    """Return the target DM schema named in a dm+dmPython URL, or None.

    Mirrors bisheng connection.py::_normalize_dm_url: the schema may be given as a
    ?schema= query param (DaMeng's connect kwarg, preferred) or a legacy /SCHEMA
    path; an explicit ?schema= wins. None means "use the login user's own schema".
    The schema is also applied explicitly to reflection/DML (OWNER=:schema /
    "SCHEMA"."TABLE") so a one-account/multi-schema deployment targets the right
    schema regardless of the login user.
    """
    if "dm+dmPython" not in url:
        return None
    parsed = sa.make_url(url)
    schema = parsed.query.get("schema") or parsed.database
    if isinstance(schema, (tuple, list)):  # a repeated ?schema= yields a tuple
        schema = schema[0] if schema else None
    return schema or None


def _dm_connect_url(url: str) -> str:
    """Build the DM connect URL: carry the schema via ?schema=, clear the path.

    Mirrors bisheng connection.py::_normalize_dm_url. dmPython.connect() rejects a
    URL *path* (SQLAlchemy maps it to the 'database' kwarg) but accepts the schema
    via the query string, which dmSQLAlchemy passes straight through to connect();
    both the sync (dmPython) and async (dmAsync) dialects accept schema=. So move
    any /SCHEMA path into ?schema= and clear the path (an existing ?schema= wins).
    Non-DM URLs are returned unchanged.
    """
    if "dm+dmPython" not in url:
        return url
    parsed = sa.make_url(url)
    schema = parsed.query.get("schema") or parsed.database
    if isinstance(schema, (tuple, list)):
        schema = schema[0] if schema else None
    new = parsed._replace(database=None)  # None means "keep"; _replace forces clear
    if schema:
        query = {k: v for k, v in new.query.items() if k != "schema"}
        query["schema"] = schema
        new = new.set(query=query)
    return new.render_as_string(hide_password=False)


def resolve_dm_schema(conn, schema_hint: str) -> str:
    """Resolve schema_hint to the actual OWNER as stored in the DM catalog.

    DM stores unquoted identifiers UPPERCASE; quoted ones keep their case. Match
    the hint case-insensitively against the schemas that actually own tables. Fail
    loudly (listing the available schemas) if there is no match — a typo in the
    ?schema= value would otherwise silently reflect zero tables and migrate
    nothing, or write into the wrong (login-user) schema.
    """
    owners = [r[0] for r in conn.execute(text("SELECT DISTINCT OWNER FROM SYS.ALL_TABLES"))]
    if schema_hint in owners:
        return schema_hint
    by_lower = {o.lower(): o for o in owners}
    if schema_hint.lower() in by_lower:
        return by_lower[schema_hint.lower()]
    raise SystemExit(
        f"DM schema '{schema_hint}' not found (no tables under that OWNER). "
        f"Available schemas: {sorted(owners)}. Fix the ?schema= in target_url."
    )


def _mask(url: str) -> str:
    """Hide the password when logging a DSN."""

    return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1***\2", url)


def _warn_source_table_collisions(jobs: list[DbJob]) -> None:
    """Warn when the same table name lives in more than one job's source DB.

    Consolidating several logical databases into ONE DM account/schema is fine as
    long as their table names are disjoint. If two source databases share a table
    name, both jobs would write to the same DM table and the second would clobber
    or pollute the first. Reflect each source's table list up front and flag any
    overlap so the operator can fix the config before loading (especially before
    --truncate). Reflection failures here are non-fatal: the per-job run reports
    them properly later, so we only log and move on.
    """
    if len(jobs) < 2:
        return
    owners: dict[str, list[str]] = {}
    for job in jobs:
        try:
            eng = sa.create_engine(job.source_url, pool_pre_ping=True)
            for t in inspect(eng).get_table_names():
                owners.setdefault(t.lower(), []).append(job.name)
        except Exception as exc:
            log.warning("  collision pre-check: could not reflect source of '%s' (%s)", job.name, exc)
    collisions = {t: dbs for t, dbs in owners.items() if len(dbs) > 1}
    if collisions:
        log.warning("=" * 70)
        log.warning("Table-name collisions across source databases sharing one DM schema:")
        for t, dbs in sorted(collisions.items()):
            log.warning("  %-40s present in: %s", t, ", ".join(dbs))
        log.warning("These would overwrite each other on the shared DM target. Use per-job")
        log.warning("`include:`/`exclude:` lists or separate DM accounts before migrating.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MySQL -> DaMeng data migration")
    parser.add_argument("--config", required=True, help="YAML config path")
    parser.add_argument(
        "--db", action="append", default=[], help="Only migrate these database names (repeatable). Default: all."
    )
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument(
        "--truncate", action="store_true", help="DELETE FROM each target table before loading (idempotent re-runs)."
    )
    parser.add_argument(
        "--resume-from",
        metavar="TABLE",
        default=None,
        help="Skip tables before TABLE in the sorted list (use after a mid-run failure). "
        "Only valid with a single --db.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Connect, reflect and count rows but write nothing.")
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create the DM tables from the MySQL schema (reflect + create_all, idempotent) "
        "before loading data. Does not create bisheng's update_time/computed triggers "
        "(the bisheng app adds those at first startup) or the DM user/schema itself.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verification only: compare per-table row counts between MySQL and DM, copy nothing.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    jobs = load_jobs(args.config)
    if args.db:
        jobs = [j for j in jobs if j.name in args.db]
        if not jobs:
            log.error("No matching database for --db %s", args.db)
            return 2

    _warn_source_table_collisions(jobs)

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
            run_job(
                job,
                args.batch_size,
                args.truncate,
                args.dry_run,
                args.resume_from,
                args.create_schema,
            )
        except Exception:
            log.exception("Migration FAILED for database %s", job.name)
            return 1
    log.info("All migrations finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
