"""Per-app data plane — the manager's read/write access to an app's SQLite (D10-C).

The app's database is one file, ``{data_root}/apps/{app_id}/db/app.db`` (the
host side of the ``/data`` volume, see ``lifecycle``). The platform backend
never opens it: it does not know the volume layout (K1) and in the multi-node
shape it is not even on the same machine — the argument D14 makes for logs
holds for the database word for word. So this module is the *only* reader and
writer outside the application itself, and the backend's ``AppDataService``
reaches it through the RPC in ``api/appdb.py``.

What :class:`AppDbService` offers is deliberately small and **typed** — table
list, table shape, paged rows, one-row update, CSV export. There is no
statement endpoint and no parameter anywhere that carries SQL: every identifier
is checked against the live ``sqlite_master`` before it is quoted into a
statement, so ``CREATE`` / ``ALTER`` / ``DROP`` / ``PRAGMA`` are not *rejected*,
they are *inexpressible*. **The data tab can never change a schema.**

Schema evolution belongs to the publish pipeline, and it arrives here as
:class:`AppDbSchemaService` — a second class in this module, reached through
``POST /v1/intents/db-migrate`` rather than through the data plane's routes
(F055 T062 / AC-42). It is in *this* file for one reason: ``sqlite3`` has
exactly one importer inside the manager, and ``test_appdb.py`` pins that. Its
input is a **declarative plan** (create this table, add these columns, rebuild
that one to this shape) — still no SQL on the wire, still every identifier and
every declared type checked before it is quoted.

Two SQLite facts shape the connection handling:

* **The app is writing to this file at the same time.** WAL allows one writer
  at a time; a long-lived write transaction here would stall the app's own
  writes. Every call opens its own connection, does its work in autocommit or
  one short ``BEGIN IMMEDIATE`` block, and closes. Reads open the file
  ``mode=ro``; writes ``mode=rw`` — never ``rwc``, because creating the file on
  the app's behalf would hand the app an empty database it did not make. The
  one exception is the migration path, where creating it *is* the job: the
  platform declares the tables and the platform builds them (DEV-07 ②), and on
  a first release that has to happen before the app has ever run.
* **``busy_timeout``** is set on every connection, so a write that arrives while
  the app holds the lock waits briefly instead of failing at once. A wait that
  still times out is reported as ``data_busy`` — a retryable answer, not an
  error the platform should hide.
"""

from __future__ import annotations

import csv
import logging
import re
import sqlite3
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runtime_manager.config import Config
from runtime_manager.errors import (
    DatabaseNotFoundError,
    DataBusyError,
    DataInvalidError,
    RowNotFoundError,
    RuntimeManagerError,
    SchemaMigrationFailedError,
    TableNotFoundError,
)

logger = logging.getLogger(__name__)

DB_FILENAME = "app.db"

#: How long a connection waits for the app's write lock before giving up.
BUSY_TIMEOUT_MS = 3000

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

#: Identifiers the platform will *look up* — the lookup itself is against
#: ``sqlite_master`` / ``PRAGMA table_info``, this regex only stops obviously
#: hostile input from reaching the quoting layer at all.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: ``app_id`` is a path segment on disk as well as in the URL.
_APP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

#: Column key used when the table has no single-column primary key.
ROWID = "rowid"

#: Declared column types whose values are binary and therefore not editable
#: through a text form (and not representable in JSON without an encoding).
_BLOB_TYPES = ("BLOB",)

_SCALAR_TYPES = (str, int, float, bool, type(None))


def _quote(identifier: str) -> str:
    """Double-quote an identifier that has already passed the whitelist check."""
    return '"' + identifier.replace('"', '""') + '"'


def _check_identifier(name: str, *, what: str) -> str:
    if not isinstance(name, str) or not _IDENTIFIER.match(name):
        raise DataInvalidError(f"{what} {name!r} is not a plain identifier")
    if name.lower().startswith("sqlite_"):
        raise DataInvalidError(f"{what} {name!r} is reserved by SQLite")
    return name


@dataclass(slots=True)
class ColumnInfo:
    name: str
    type: str
    notnull: bool
    default: Any
    pk: int

    @property
    def is_blob(self) -> bool:
        return any(marker in (self.type or "").upper() for marker in _BLOB_TYPES)

    def to_response(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "notnull": self.notnull,
            "default": self.default,
            "pk": self.pk,
            "editable": not self.is_blob,
        }


@dataclass(slots=True)
class TableShape:
    """A table as the platform sees it: columns plus the key rows are addressed by."""

    name: str
    columns: list[ColumnInfo]
    #: Column the PATCH endpoint addresses a row by. ``rowid`` when the table
    #: has no single-column primary key (SQLite rowid tables always have one).
    key: str
    #: ``False`` for a ``WITHOUT ROWID`` table with a composite key — nothing
    #: identifies one row, so it can be read and exported but not edited.
    editable: bool = True
    column_names: set[str] = field(default_factory=set)
    #: Declared primary-key columns in key order (empty for a keyless table).
    pk_columns: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.column_names = {column.name for column in self.columns}
        self.pk_columns = [column.name for column in sorted(self.columns, key=lambda c: c.pk) if column.pk]

    @property
    def key_is_rowid(self) -> bool:
        return self.key == ROWID

    @property
    def tiebreakers(self) -> list[str]:
        """Columns that make an ORDER BY total: the row key, or every key column
        of a composite-key table (which has no single row address but still
        has a unique tuple)."""
        return [self.key] if self.editable else self.pk_columns

    def to_response(self) -> dict[str, Any]:
        return {
            "table": self.name,
            "columns": [column.to_response() for column in self.columns],
            "key": {"column": self.key, "kind": "rowid" if self.key_is_rowid else "primary_key"},
            "editable": self.editable,
        }


def _json_value(value: Any) -> Any:
    """SQLite values are JSON scalars already, except BLOBs."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<blob {len(value)} bytes>"
    return value


class AppDbService:
    """Typed operations on one app's database. One connection per call."""

    def __init__(self, config: Config) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # paths & connections
    # ------------------------------------------------------------------

    def db_path(self, app_id: str) -> Path:
        if not _APP_ID.match(app_id or ""):
            raise DataInvalidError(f"app_id {app_id!r} is not a valid identifier")
        return self._config.app_data_dir(app_id) / DB_FILENAME

    def _connect(self, app_id: str, *, write: bool = False) -> sqlite3.Connection:
        path = self.db_path(app_id)
        if not path.is_file():
            # The app creates its own database on first use; until then there is
            # nothing to show, and creating an empty one here would be a lie.
            raise DatabaseNotFoundError(f"app {app_id} has not created its database yet")
        mode = "rw" if write else "ro"
        try:
            conn = sqlite3.connect(
                f"file:{path}?mode={mode}",
                uri=True,
                timeout=BUSY_TIMEOUT_MS / 1000,
                isolation_level=None,  # autocommit; write paths open their own short transaction
            )
        except sqlite3.OperationalError as exc:
            raise DataBusyError(f"cannot open the database of app {app_id}: {exc}")
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        return conn

    @staticmethod
    def _translate(app_id: str, exc: sqlite3.Error) -> RuntimeManagerError:
        """SQLite's own failures as data-plane answers, not a 500.

        A WAL reader is only ever locked out by an exclusive operation of the
        app's (VACUUM, a truncating checkpoint) — retryable, so ``data_busy``.
        Anything else SQLite refuses (a file that is not a database, a
        constraint) is ``data_invalid``: the request cannot be served as
        stated, and the platform must not read it as "the orchestrator is
        unavailable".
        """
        text = str(exc).lower()
        if isinstance(exc, sqlite3.OperationalError) and ("locked" in text or "busy" in text):
            return DataBusyError(f"the database of app {app_id} is busy: {exc}")
        if isinstance(exc, sqlite3.IntegrityError):
            return DataInvalidError(f"update violates a constraint: {exc}")
        return DataInvalidError(f"rejected by SQLite: {exc}")

    # ------------------------------------------------------------------
    # shape
    # ------------------------------------------------------------------

    def list_tables(self, app_id: str) -> list[dict[str, Any]]:
        """User tables only — SQLite's own bookkeeping tables are not the app's data."""
        conn = self._connect(app_id)
        try:
            names = self._table_names(conn)
            return [{"name": name, "column_count": len(self._shape(conn, name).columns)} for name in names]
        except sqlite3.Error as exc:
            raise self._translate(app_id, exc) from exc
        finally:
            conn.close()

    def table_schema(self, app_id: str, table: str) -> dict[str, Any]:
        conn = self._connect(app_id)
        try:
            return self._resolve(conn, table).to_response()
        except sqlite3.Error as exc:
            raise self._translate(app_id, exc) from exc
        finally:
            conn.close()

    @staticmethod
    def _table_names(conn: sqlite3.Connection) -> list[str]:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [row["name"] for row in rows]

    def _resolve(self, conn: sqlite3.Connection, table: str) -> TableShape:
        """The whitelist check: the name must be a real table in *this* file."""
        _check_identifier(table, what="table")
        if table not in self._table_names(conn):
            raise TableNotFoundError(f"table {table!r} does not exist")
        return self._shape(conn, table)

    @staticmethod
    def _shape(conn: sqlite3.Connection, table: str) -> TableShape:
        columns = [
            ColumnInfo(
                name=row["name"],
                type=row["type"] or "",
                notnull=bool(row["notnull"]),
                default=row["dflt_value"],
                pk=int(row["pk"] or 0),
            )
            for row in conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
        ]
        pk_columns = [column.name for column in sorted(columns, key=lambda c: c.pk) if column.pk]
        if len(pk_columns) == 1:
            return TableShape(name=table, columns=columns, key=pk_columns[0])
        # No single key column: a rowid table is addressed by rowid; a WITHOUT
        # ROWID table with a composite key has no single row address at all.
        without_rowid = bool(
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? AND sql LIKE '%WITHOUT ROWID%'",
                (table,),
            ).fetchone()
        )
        if without_rowid:
            return TableShape(name=table, columns=columns, key=pk_columns[0] if pk_columns else "", editable=False)
        return TableShape(name=table, columns=columns, key=ROWID)

    # ------------------------------------------------------------------
    # rows
    # ------------------------------------------------------------------

    def rows(
        self,
        app_id: str,
        table: str,
        *,
        page: int = 1,
        size: int = DEFAULT_PAGE_SIZE,
        order: str | None = None,
    ) -> dict[str, Any]:
        """One page, in a **stable** order.

        ``order`` is ``column`` or ``-column``; the row key is always appended
        as the tiebreaker so two pages never overlap and never skip a row —
        ORDER BY a non-unique column alone leaves ties in arbitrary order.
        """
        page = max(int(page or 1), 1)
        size = min(max(int(size or DEFAULT_PAGE_SIZE), 1), MAX_PAGE_SIZE)
        conn = self._connect(app_id)
        try:
            shape = self._resolve(conn, table)
            order_sql = self._order_clause(shape, order)
            key_select = self._key_select(shape)
            total = conn.execute(f"SELECT COUNT(*) AS n FROM {_quote(table)}").fetchone()["n"]
            cursor = conn.execute(
                f"SELECT {key_select}, * FROM {_quote(table)} {order_sql} LIMIT ? OFFSET ?",
                (size, (page - 1) * size),
            )
            rows = [self._row_payload(shape, row) for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            raise self._translate(app_id, exc) from exc
        finally:
            conn.close()
        return {"rows": rows, "total": int(total), "page": page, "size": size, "order": order or ""}

    @staticmethod
    def _key_select(shape: TableShape) -> str:
        if not shape.editable:
            return "NULL AS __key"
        return f"{_quote(shape.key)} AS __key"

    @staticmethod
    def _row_payload(shape: TableShape, row: sqlite3.Row) -> dict[str, Any]:
        values = {column.name: _json_value(row[column.name]) for column in shape.columns}
        return {"key": _json_value(row["__key"]), "values": values}

    @staticmethod
    def _order_clause(shape: TableShape, order: str | None) -> str:
        parts: list[str] = []
        if order:
            descending = order.startswith("-")
            column = _check_identifier(order[1:] if descending else order, what="order column")
            if column not in shape.column_names and column != ROWID:
                raise DataInvalidError(f"order column {column!r} does not exist in table {shape.name!r}")
            parts.append(f"{_quote(column)} {'DESC' if descending else 'ASC'}")
        ordered = order.lstrip("-") if order else None
        parts.extend(f"{_quote(column)} ASC" for column in shape.tiebreakers if column != ordered)
        return ("ORDER BY " + ", ".join(parts)) if parts else ""

    def update_row(self, app_id: str, table: str, key: str, values: dict[str, Any]) -> dict[str, Any]:
        """Change one row, and only one — ``rowcount != 1`` rolls back.

        Returns ``before`` / ``after`` for the submitted columns so the backend
        can write the audit row without a second read (which could already see
        the app's next write).
        """
        if not isinstance(values, dict) or not values:
            raise DataInvalidError("values must be a non-empty object of column → value")
        conn = self._connect(app_id, write=True)
        try:
            shape = self._resolve(conn, table)
            if not shape.editable:
                raise DataInvalidError(f"table {table!r} has no single-column key; rows cannot be addressed")
            assignments = self._assignments(shape, values)
            key_value = self._coerce_key(shape, key)
            key_sql = _quote(shape.key)
            columns_sql = ", ".join(_quote(name) for name in assignments)
            try:
                conn.execute("BEGIN IMMEDIATE")
                before = conn.execute(
                    f"SELECT {columns_sql} FROM {_quote(table)} WHERE {key_sql} = ?", (key_value,)
                ).fetchall()
                if len(before) != 1:
                    conn.execute("ROLLBACK")
                    if not before:
                        raise RowNotFoundError(f"no row with {shape.key} = {key!r} in table {table!r}")
                    raise DataInvalidError(f"{shape.key} = {key!r} matches {len(before)} rows in table {table!r}")
                set_sql = ", ".join(f"{_quote(name)} = ?" for name in assignments)
                cursor = conn.execute(
                    f"UPDATE {_quote(table)} SET {set_sql} WHERE {key_sql} = ?",
                    (*assignments.values(), key_value),
                )
                if cursor.rowcount != 1:
                    conn.execute("ROLLBACK")
                    raise RowNotFoundError(f"update touched {cursor.rowcount} rows, expected 1 — nothing was written")
                after = conn.execute(
                    f"SELECT {columns_sql} FROM {_quote(table)} WHERE {key_sql} = ?", (key_value,)
                ).fetchone()
                conn.execute("COMMIT")
            except sqlite3.Error as exc:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise self._translate(app_id, exc) from exc
        finally:
            conn.close()
        names = list(assignments)
        return {
            "table": table,
            "key": _json_value(key_value),
            "before": {name: _json_value(before[0][name]) for name in names},
            "after": {name: _json_value(after[name]) for name in names},
        }

    @staticmethod
    def _assignments(shape: TableShape, values: dict[str, Any]) -> dict[str, Any]:
        by_name = {column.name: column for column in shape.columns}
        assignments: dict[str, Any] = {}
        for name, value in values.items():
            _check_identifier(str(name), what="column")
            column = by_name.get(name)
            if column is None:
                raise DataInvalidError(f"column {name!r} does not exist in table {shape.name!r}")
            if name == shape.key:
                raise DataInvalidError(f"column {name!r} is the row key and cannot be changed here")
            if column.is_blob:
                raise DataInvalidError(f"column {name!r} is binary and cannot be edited as text")
            if not isinstance(value, _SCALAR_TYPES):
                raise DataInvalidError(f"column {name!r}: only scalar values are accepted")
            assignments[name] = value
        return assignments

    @staticmethod
    def _coerce_key(shape: TableShape, key: str) -> Any:
        """The key arrives as a path segment (text). ``rowid`` is an integer."""
        text = str(key)
        if shape.key_is_rowid:
            if not re.match(r"^-?\d+$", text):
                raise DataInvalidError(f"rowid {key!r} is not an integer")
            return int(text)
        column = next((column for column in shape.columns if column.name == shape.key), None)
        declared = (column.type if column else "").upper()
        if "INT" in declared and re.match(r"^-?\d+$", text):
            return int(text)
        return text

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------

    def export_csv(self, app_id: str, table: str) -> Path:
        """Write the whole table to ``{data_root}/exports/{app_id}/`` and return the path.

        Streamed row by row through one autocommit SELECT: a read transaction
        in WAL mode never blocks the app's writer, only a checkpoint, so a big
        table costs time and disk but never availability. The caller removes
        the file once it has been sent.
        """
        conn = self._connect(app_id)
        target: Path | None = None
        try:
            shape = self._resolve(conn, table)
            target_dir = self._config.data_root / "exports" / app_id
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{table}-{int(time.time())}.csv"
            order_sql = self._order_clause(shape, None)
            with target.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow([column.name for column in shape.columns])
                cursor = conn.execute(f"SELECT * FROM {_quote(table)} {order_sql}")
                for row in cursor:
                    writer.writerow([_json_value(row[column.name]) for column in shape.columns])
        except sqlite3.Error as exc:
            if target is not None:
                target.unlink(missing_ok=True)  # a half-written export must not be served
            raise self._translate(app_id, exc) from exc
        finally:
            conn.close()
        logger.info("app_db export app_id=%s table=%s file=%s", app_id, table, target)
        return target


# ---------------------------------------------------------------------------
# schema evolution — the publish pipeline's half (F055 T062 / AC-42)
# ---------------------------------------------------------------------------

#: Where a pre-migration copy of the production data lands (F054 design D10).
#: One tar per migration, named by the epoch second it was taken.
SNAPSHOT_KEY_TEMPLATE = "apps/{app_id}/db-snapshots/{ts}.tar"

#: The single member inside that tar. Fixed so a restore is "untar, put it back".
SNAPSHOT_MEMBER = "app.db"

#: Plan verbs. The platform derives them by diffing two manifests; this module
#: is the only place one of them becomes SQL.
PLAN_CREATE_TABLE = "create_table"
PLAN_ADD_COLUMNS = "add_columns"
PLAN_REBUILD_TABLE = "rebuild_table"
PLAN_DROP_TABLE = "drop_table"
PLAN_OPS: frozenset[str] = frozenset({PLAN_CREATE_TABLE, PLAN_ADD_COLUMNS, PLAN_REBUILD_TABLE, PLAN_DROP_TABLE})

#: Verbs that can lose production rows. A plan containing one of these takes a
#: snapshot **whether or not the caller asked for one** — 「迁移前自动留生产数据
#: 快照」 is a promise to the owner, and a promise that depends on the caller
#: remembering a flag is not one.
DESTRUCTIVE_OPS: frozenset[str] = frozenset({PLAN_REBUILD_TABLE, PLAN_DROP_TABLE})

#: Suffix of the scratch table a rebuild goes through. Long enough that it
#: cannot collide with a declared name, and dropped again either way.
_REBUILD_SUFFIX = "__bisheng_migrating"

#: A declared column type, as it may be quoted into DDL. SQLite accepts any
#: string as a type name (affinity is derived from substrings), so the check is
#: not "is this a known type" but "is this a *type name* rather than a
#: statement": letters and spaces, optionally one size suffix.
_DECLARED_TYPE = re.compile(r"^[A-Za-z][A-Za-z ]{0,30}(\(\s*\d{1,5}\s*(,\s*\d{1,5}\s*)?\))?$")


@dataclass(slots=True, frozen=True)
class _PlanItem:
    """One validated plan entry. Nothing reaches SQL that did not pass through here."""

    op: str
    table: str
    columns: tuple[dict[str, Any], ...] = ()


def _migration_failed(message: str, **extra: Any) -> SchemaMigrationFailedError:
    return SchemaMigrationFailedError(message, **extra)


def _default_literal(value: Any) -> str:
    """A declared default as a SQL literal.

    ``DEFAULT`` is part of the DDL text and cannot be a bound parameter, so this
    is the one place a *value* is written into a statement — hence the closed
    set of accepted types and the doubled quote. Anything else is refused
    rather than coerced: a default the platform cannot spell exactly is a
    default the application would silently not get.
    """
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise _migration_failed(f"default value {value!r} is not a string, number or boolean", reason="invalid_default")


class AppDbSchemaService:
    """Apply a declarative table plan to one app's database (AC-42).

    Three properties the tests pin, because each is a way this could quietly do
    the wrong thing:

    * **The snapshot happens before the first DDL statement, or the migration
      does not happen at all.** A destructive plan whose snapshot could not be
      stored is refused — reporting "migrated" after failing to preserve the
      rows the confirmation was asked about would make AC-42 a lie.
    * **The whole plan is one transaction.** SQLite is transactional over DDL,
      so a plan that fails half way leaves the database exactly as it was;
      there is no "partially migrated" state for anyone to diagnose.
    * **Every step is idempotent.** ``manual_publish`` retries the same version
      after a parked release, so the same plan reaches this method again: an
      existing table is not re-created, an existing column is not re-added, and
      a rebuild re-derives the same shape.
    """

    def __init__(self, config: Config, store: Any | None = None) -> None:
        self._config = config
        self._store = store

    # ------------------------------------------------------------------
    # entry point
    # ------------------------------------------------------------------

    def migrate(self, app_id: str, plan: list[dict[str, Any]], *, snapshot: bool = False) -> dict[str, Any]:
        """Bring the app's tables to the declared shape. Returns what was done.

        ``snapshot`` only ever *adds* a snapshot: a destructive plan takes one
        regardless (see :data:`DESTRUCTIVE_OPS`).
        """
        items = self._validate(plan)
        if not items:
            return {"applied": [], "skipped": [], "snapshot_key": None}

        path = self.db_path(app_id)
        existed = path.is_file()
        wanted = snapshot or any(item.op in DESTRUCTIVE_OPS for item in items)
        conn = self._connect_for_migration(app_id, path)
        snapshot_key: str | None = None
        try:
            if wanted and existed:
                # Nothing to preserve when the file is ours to create: a first
                # release has no production data, and an empty tar would only
                # make the snapshot list harder to read.
                snapshot_key = self._store_snapshot(app_id, conn)
            applied, skipped = self._apply(conn, items)
        finally:
            conn.close()
        logger.info(
            "app_db migrate app_id=%s applied=%s skipped=%s snapshot=%s",
            app_id,
            len(applied),
            len(skipped),
            snapshot_key or "-",
        )
        return {"applied": applied, "skipped": skipped, "snapshot_key": snapshot_key}

    def db_path(self, app_id: str) -> Path:
        if not _APP_ID.match(app_id or ""):
            raise DataInvalidError(f"app_id {app_id!r} is not a valid identifier")
        return self._config.app_data_dir(app_id) / DB_FILENAME

    # ------------------------------------------------------------------
    # validation — everything refusable without touching the file
    # ------------------------------------------------------------------

    def _validate(self, plan: Any) -> list[_PlanItem]:
        """Check the whole plan up front.

        Up front matters: a plan rejected half way would already have taken a
        snapshot and possibly created a table, so "the release was refused" and
        "the database was left alone" would stop being the same sentence.
        """
        if plan is None:
            return []
        if not isinstance(plan, list):
            raise _migration_failed("plan must be a list of operations", reason="invalid_plan")
        items: list[_PlanItem] = []
        for entry in plan:
            if not isinstance(entry, dict):
                raise _migration_failed("every plan entry must be an object", reason="invalid_plan")
            op = str(entry.get("op") or "")
            if op not in PLAN_OPS:
                raise _migration_failed(f"unknown plan operation {op!r}", reason="invalid_plan", op=op)
            table = self._identifier(str(entry.get("table") or ""), what="table")
            columns = () if op == PLAN_DROP_TABLE else self._columns(table, entry.get("columns"), op=op)
            items.append(_PlanItem(op=op, table=table, columns=columns))
        return items

    def _identifier(self, name: str, *, what: str) -> str:
        try:
            return _check_identifier(name, what=what)
        except DataInvalidError as exc:
            raise _migration_failed(str(exc.detail.get("message") or exc), reason="invalid_identifier") from exc

    def _columns(self, table: str, raw: Any, *, op: str) -> tuple[dict[str, Any], ...]:
        if not isinstance(raw, list) or not raw:
            raise _migration_failed(
                f"operation {op!r} on table {table!r} carries no columns", reason="invalid_plan", table=table
            )
        seen: set[str] = set()
        columns: list[dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                raise _migration_failed(f"column entry of table {table!r} is not an object", reason="invalid_plan")
            name = self._identifier(str(entry.get("name") or ""), what="column")
            if name in seen:
                raise _migration_failed(
                    f"column {name!r} is declared twice on table {table!r}", reason="invalid_plan", table=table
                )
            seen.add(name)
            columns.append(
                {
                    "name": name,
                    "type": self._declared_type(table, name, entry.get("type")),
                    "nullable": entry.get("nullable"),
                    "default": entry.get("default"),
                    "primary_key": bool(entry.get("primary_key")),
                }
            )
        return tuple(columns)

    def _declared_type(self, table: str, column: str, declared: Any) -> str:
        if declared is None or declared == "":
            # A column with no declared type is legal SQLite (blank affinity)
            # and is exactly what ``columns: [id, name]`` in a manifest means.
            return ""
        text = str(declared).strip()
        if not _DECLARED_TYPE.match(text):
            raise _migration_failed(
                f"column {column!r} of table {table!r} declares type {text!r}, which is not a type name",
                reason="invalid_type",
                table=table,
                column=column,
            )
        return text

    # ------------------------------------------------------------------
    # the snapshot
    # ------------------------------------------------------------------

    def _store_snapshot(self, app_id: str, conn: sqlite3.Connection) -> str:
        """A consistent copy of the live database, tarred and stored (AC-42).

        ``Connection.backup`` rather than ``tar app.db``: the file on disk is
        half of a WAL database, and archiving it while the application is
        writing produces a copy that is *not* a database. The copy is taken
        through the same connection the migration will run on, which is also
        what makes it the state the migration is about to change.
        """
        from runtime_manager.storage import ensure_private_bucket, get_object_store

        ts = int(time.time())
        key = SNAPSHOT_KEY_TEMPLATE.format(app_id=app_id, ts=ts)
        staging = self._config.data_root / "db-snapshots" / app_id
        staging.mkdir(parents=True, exist_ok=True)
        copy = staging / f"{ts}-{SNAPSHOT_MEMBER}"
        archive = staging / f"{ts}.tar"
        try:
            target = sqlite3.connect(copy)
            try:
                conn.backup(target)
            finally:
                target.close()
            with tarfile.open(archive, "w") as tar:
                tar.add(copy, arcname=SNAPSHOT_MEMBER)
            store = self._store if self._store is not None else get_object_store()
            bucket = self._config.storage_bucket
            ensure_private_bucket(store, bucket)
            store.put_object(bucket, key, archive.read_bytes(), "application/x-tar")
        except RuntimeManagerError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            raise _migration_failed(
                f"the pre-migration data snapshot could not be stored: {detail.get('message') or exc}",
                reason="snapshot_failed",
            ) from exc
        except Exception as exc:
            raise _migration_failed(
                f"the pre-migration data snapshot could not be taken: {exc}", reason="snapshot_failed"
            ) from exc
        finally:
            copy.unlink(missing_ok=True)
            archive.unlink(missing_ok=True)
        logger.info("app_db snapshot app_id=%s key=%s", app_id, key)
        return key

    # ------------------------------------------------------------------
    # the DDL
    # ------------------------------------------------------------------

    def _connect_for_migration(self, app_id: str, path: Path) -> sqlite3.Connection:
        """``rwc`` — the one path allowed to create the file (DEV-07 ②)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(
                f"file:{path}?mode=rwc", uri=True, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None
            )
        except sqlite3.OperationalError as exc:
            raise DataBusyError(f"cannot open the database of app {app_id}: {exc}")
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        return conn

    def _apply(
        self, conn: sqlite3.Connection, items: list[_PlanItem]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        try:
            conn.execute("BEGIN IMMEDIATE")
            for item in items:
                outcome = self._apply_one(conn, item)
                (skipped if outcome.get("skipped") else applied).append(outcome)
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            self._rollback(conn)
            raise _migration_failed(f"rejected by SQLite: {exc}", reason="sqlite_error") from exc
        except RuntimeManagerError:
            self._rollback(conn)
            raise
        return applied, skipped

    @staticmethod
    def _rollback(conn: sqlite3.Connection) -> None:
        if conn.in_transaction:
            conn.execute("ROLLBACK")

    def _apply_one(self, conn: sqlite3.Connection, item: _PlanItem) -> dict[str, Any]:
        live = self._live_columns(conn, item.table)
        if item.op == PLAN_DROP_TABLE:
            if live is None:
                return {"op": item.op, "table": item.table, "skipped": "absent"}
            conn.execute(f"DROP TABLE {_quote(item.table)}")
            return {"op": item.op, "table": item.table}

        if live is None:
            # Missing table, whatever the verb said: creating it is where every
            # verb was trying to end up, and it makes a retry after a release
            # that died half way do the right thing.
            self._create(conn, item.table, item.columns)
            return {"op": PLAN_CREATE_TABLE, "table": item.table, "columns": [c["name"] for c in item.columns]}

        if item.op == PLAN_CREATE_TABLE:
            return {"op": item.op, "table": item.table, "skipped": "exists"}

        if item.op == PLAN_ADD_COLUMNS:
            added = self._add_columns(conn, item.table, item.columns, live)
            if not added:
                return {"op": item.op, "table": item.table, "skipped": "exists"}
            return {"op": item.op, "table": item.table, "columns": added}

        self._rebuild(conn, item.table, item.columns, live)
        return {"op": item.op, "table": item.table, "columns": [c["name"] for c in item.columns]}

    @staticmethod
    def _live_columns(conn: sqlite3.Connection, table: str) -> list[str] | None:
        """Column names of ``table``, or ``None`` when the table does not exist."""
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
        if not exists:
            return None
        return [row["name"] for row in conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()]

    def _create(self, conn: sqlite3.Connection, table: str, columns: tuple[dict[str, Any], ...]) -> None:
        body = ", ".join(self._column_ddl(column) for column in columns)
        conn.execute(f"CREATE TABLE {_quote(table)} ({body})")

    def _add_columns(
        self, conn: sqlite3.Connection, table: str, columns: tuple[dict[str, Any], ...], live: list[str]
    ) -> list[str]:
        added: list[str] = []
        for column in columns:
            if column["name"] in live:
                continue
            self._require_fillable(table, column)
            conn.execute(f"ALTER TABLE {_quote(table)} ADD COLUMN {self._column_ddl(column)}")
            added.append(column["name"])
        return added

    def _rebuild(
        self, conn: sqlite3.Connection, table: str, columns: tuple[dict[str, Any], ...], live: list[str]
    ) -> None:
        """SQLite's supported way to change or drop a column: build, copy, swap.

        ``ALTER TABLE … DROP COLUMN`` exists in newer SQLite versions and still
        cannot change a type, so a rebuild is needed for half the breaking
        cases anyway — doing all of them the same way means one code path has
        to get the copy step right instead of two.
        """
        for column in columns:
            if column["name"] not in live:
                self._require_fillable(table, column)
        carried = [column["name"] for column in columns if column["name"] in live]
        scratch = f"{table}{_REBUILD_SUFFIX}"
        conn.execute(f"DROP TABLE IF EXISTS {_quote(scratch)}")
        self._create(conn, scratch, columns)
        if carried:
            names = ", ".join(_quote(name) for name in carried)
            conn.execute(f"INSERT INTO {_quote(scratch)} ({names}) SELECT {names} FROM {_quote(table)}")
        conn.execute(f"DROP TABLE {_quote(table)}")
        conn.execute(f"ALTER TABLE {_quote(scratch)} RENAME TO {_quote(table)}")

    @staticmethod
    def _require_fillable(table: str, column: dict[str, Any]) -> None:
        """A new NOT NULL column needs a default — existing rows have no value.

        Refused rather than quietly relaxed to nullable: the declaration is the
        contract the application's own code is written against, and a column
        that is nullable in production but NOT NULL in the manifest is a bug
        that surfaces much later and much further away.
        """
        if column["nullable"] is False and column["default"] is None and not column["primary_key"]:
            raise _migration_failed(
                f"column {column['name']!r} of table {table!r} is declared NOT NULL without a default, "
                "so existing rows would have no value for it",
                reason="notnull_without_default",
                table=table,
                column=column["name"],
            )

    @staticmethod
    def _column_ddl(column: dict[str, Any]) -> str:
        parts = [_quote(column["name"])]
        if column["type"]:
            parts.append(column["type"])
        if column["primary_key"]:
            parts.append("PRIMARY KEY")
        if column["nullable"] is False:
            parts.append("NOT NULL")
        if column["default"] is not None:
            parts.append(f"DEFAULT {_default_literal(column['default'])}")
        return " ".join(parts)
