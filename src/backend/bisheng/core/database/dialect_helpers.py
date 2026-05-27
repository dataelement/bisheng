"""Dialect-agnostic helpers for DaMeng + MySQL dual-database support."""
from __future__ import annotations

import json as _json
import re

import sqlalchemy as sa
from sqlalchemy import inspect, Text, CLOB, JSON
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import FunctionElement
from sqlalchemy.sql.schema import Computed
from sqlalchemy.sql.sqltypes import Boolean as _Boolean
from sqlalchemy.types import TypeDecorator


# ---------------------------------------------------------------------------
# Boolean DDL override for DaMeng
# ---------------------------------------------------------------------------
# DaMeng (Oracle-compatible) does not support the SQL BOOLEAN type.
# Map it to SMALLINT (0/1).  SQLAlchemy's Boolean type still handles
# Python True/False ↔ 1/0 conversion transparently at the driver level.
#
# @compiles dispatch does not always intercept type-compiler paths in all
# dialect configurations.  Directly patch DmTypeCompiler as a reliable fallback.

@compiles(_Boolean, "dm")
def _compile_boolean_dm(element, compiler, **kw):
    return "SMALLINT"


def _patch_dm_ddl_compiler() -> None:
    """Fix autoincrement column generation in dmSQLAlchemy DDL compiler.

    dmSQLAlchemy's get_column_specification checks `column.autoincrement == True`
    but SQLModel / SQLAlchemy default for primary-key integer columns is the
    string 'auto', not the bool True.  'auto' == True is False in Python, so
    IDENTITY(1,1) is never emitted for SQLModel-defined primary keys.

    This patch wraps the method to normalise 'auto' → True before the check.
    """
    try:
        from sqlalchemy import Integer, SmallInteger, BigInteger
        from dmSQLAlchemy.base import DMDDLCompiler  # type: ignore[import]

        _orig = DMDDLCompiler.get_column_specification

        def _patched(self, column, **kw):
            # Temporarily promote 'auto' to True for integer PK columns so
            # dmSQLAlchemy's `== True` guard emits IDENTITY(1,1).
            promoted = False
            if (column.autoincrement == 'auto'
                    and column.primary_key
                    and not column.foreign_keys   # FK columns are never autoincrement
                    and isinstance(column.type,
                                   (Integer, SmallInteger, BigInteger))):
                column.__dict__['autoincrement'] = True
                promoted = True
            try:
                return _orig(self, column, **kw)
            finally:
                if promoted:
                    column.__dict__['autoincrement'] = 'auto'

        DMDDLCompiler.get_column_specification = _patched
    except (ImportError, AttributeError):
        pass


def _patch_dm_type_compiler() -> None:
    """Directly patch DaMeng's type compiler so BOOLEAN → SMALLINT.

    This is a belt-and-suspenders fix: @compiles above handles the standard
    path; this patch covers the case where dmSQLAlchemy's DmTypeCompiler has
    its own visit_boolean that bypasses @compiles dispatch.
    """
    try:
        from dmSQLAlchemy.base import DMTypeCompiler as DmTypeCompiler  # type: ignore[import]

        def _visit_boolean(self, type_, **kw):
            return "SMALLINT"

        def _visit_longtext(self, type_, **kw):
            return "CLOB"

        def _visit_json(self, type_, **kw):
            return "CLOB"

        def _visit_char(self, type_, **kw):
            # DaMeng CHAR pads stored values to the declared length and returns
            # the padded string to the application, unlike MySQL which strips on
            # retrieval.  Emitting VARCHAR avoids padding in new DDL.
            return f"VARCHAR({type_.length or 1})"

        DmTypeCompiler.visit_boolean = _visit_boolean
        DmTypeCompiler.visit_BOOLEAN = _visit_boolean
        # LONGTEXT / JSON are MySQL-specific; fall back to CLOB on DaMeng
        DmTypeCompiler.visit_LONGTEXT = _visit_longtext
        DmTypeCompiler.visit_JSON = _visit_json
        DmTypeCompiler.visit_json = _visit_json
        # CHAR pads to declared length on DaMeng — use VARCHAR in DDL instead
        DmTypeCompiler.visit_CHAR = _visit_char

        # Tell SQLAlchemy that DaMeng has no native JSON support so it
        # serialises Python dicts to JSON strings on the Python side.
        try:
            from dmSQLAlchemy.base import DMDialect  # type: ignore[import]
            DMDialect.supports_native_json = False
        except (ImportError, AttributeError):
            pass
    except ImportError:
        pass  # Not on a DaMeng-capable platform (e.g., macOS dev)


def _patch_dm_char_stripping() -> None:
    """Patch SQLAlchemy CHAR.result_processor to strip trailing spaces on DaMeng.

    DaMeng (Oracle-compatible) returns CHAR columns right-padded to the column
    length, while MySQL silently strips on retrieval.  This patch makes DaMeng
    behave consistently with MySQL for all existing CHAR columns without
    requiring model changes.
    """
    from sqlalchemy.types import CHAR as _CHAR  # local import avoids circular refs

    _orig_result_processor = _CHAR.result_processor

    def _patched_result_processor(self, dialect, coltype):
        if dialect.name == "dm":
            def _strip(value):
                return value.rstrip() if value is not None else value
            return _strip
        return _orig_result_processor(self, dialect, coltype)

    _CHAR.result_processor = _patched_result_processor


_patch_dm_ddl_compiler()
_patch_dm_type_compiler()
_patch_dm_char_stripping()


# ---------------------------------------------------------------------------
# Computed column DDL override for DaMeng
# ---------------------------------------------------------------------------

@compiles(Computed, "dm")
def _compile_computed_dm(element, compiler, **kw):  # noqa: F811
    """On DaMeng, suppress GENERATED ALWAYS AS — the column becomes a plain
    integer whose value is maintained by a BEFORE INSERT OR UPDATE trigger
    created at application startup (_ensure_dm_computed_triggers in connection.py).
    """
    return ""


class _UpdateTimeServerDefault(FunctionElement):
    """Compile-time dialect-aware server_default for update_time columns.

    MySQL  → CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    DaMeng → CURRENT_TIMESTAMP  (triggers created at startup handle ON UPDATE)
    Others → CURRENT_TIMESTAMP

    Usage in model definitions::

        sa_column=Column(DateTime, nullable=False,
                         server_default=UPDATE_TIME_SERVER_DEFAULT)
    """
    inherit_cache = True
    name = "update_time_server_default"


@compiles(_UpdateTimeServerDefault)
def _compile_update_time_default(element, compiler, **kw):
    return "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"


@compiles(_UpdateTimeServerDefault, "dm")
def _compile_update_time_default_dm(element, compiler, **kw):
    return "CURRENT_TIMESTAMP"


@compiles(_UpdateTimeServerDefault, "sqlite")
def _compile_update_time_default_sqlite(element, compiler, **kw):
    return "CURRENT_TIMESTAMP"


# Singleton — import and use directly in sa_column definitions
UPDATE_TIME_SERVER_DEFAULT = _UpdateTimeServerDefault()


class JsonType(TypeDecorator):
    """Stores Python dicts/lists as JSON.

    MySQL: delegates to native JSON type (full ORM transparency).
    DaMeng: stores as CLOB with explicit Python-side serialize/deserialize.
    Others (SQLite, etc.): stores as TEXT with explicit serialize/deserialize.
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "mysql":
            return dialect.type_descriptor(JSON())
        if dialect.name == "dm":
            return dialect.type_descriptor(CLOB())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if dialect.name == "mysql":
            return value  # native JSON handles serialization
        if value is not None:
            return _json.dumps(value, ensure_ascii=False)
        return value

    def process_result_value(self, value, dialect):
        if dialect.name == "mysql":
            return value  # native JSON handles deserialization
        if value is not None:
            return _json.loads(value)
        return value


def json_array_contains(column, value: str, dialect_name: str):
    """Return a SQLAlchemy WHERE expression: does JSON array column contain value?

    value must be the JSON-encoded element:
      - integer 5  → pass '5'
      - string 'x' → pass '"x"' (with JSON quotes)

    MySQL: uses func.json_contains (native, index-friendly).
    DaMeng/others: uses LIKE against the CLOB text serialized by JsonType.
    """
    if dialect_name == "mysql":
        return sa.func.json_contains(column, value)

    text_col = sa.cast(column, Text())
    v = str(value)
    if v.startswith('"') and v.endswith('"'):
        # JSON-quoted string — quoted form is unique enough for LIKE
        return text_col.like(f"%{v}%")
    # Integer — match at JSON array element boundaries
    # JsonType serializes with Python default separator ", "
    return sa.or_(
        text_col == f"[{v}]",
        text_col.like(f"[{v}, %"),
        text_col.like(f"%, {v}]"),
        text_col.like(f"%, {v}, %"),
    )


def json_search_exists(column, value: str, dialect_name: str):
    """Return expression: does JSON column contain value anywhere (JSON_SEARCH equivalent)?

    MySQL: json_search(...).isnot(None).
    DaMeng/others: LIKE on the CLOB text.
    """
    if dialect_name == "mysql":
        return sa.func.json_search(column, "all", value).isnot(None)
    return sa.cast(column, Text()).like(f"%{value}%")


def get_dialect_name(conn_or_engine) -> str:
    """Return the SQLAlchemy dialect name: 'mysql' | 'dm' | 'sqlite' | 'postgresql'."""
    if hasattr(conn_or_engine, "dialect"):
        return conn_or_engine.dialect.name
    return conn_or_engine.name


class LargeText(TypeDecorator):
    """Maps to LONGTEXT on MySQL, CLOB on DaMeng, TEXT on all others."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "mysql":
            return dialect.type_descriptor(LONGTEXT())
        if dialect.name == "dm":
            return dialect.type_descriptor(CLOB())
        return dialect.type_descriptor(Text())


def table_exists(conn, table_name: str) -> bool:
    try:
        return inspect(conn).has_table(table_name)
    except Exception:
        return False


def column_exists(conn, table_name: str, column_name: str) -> bool:
    try:
        cols = [c["name"].lower() for c in inspect(conn).get_columns(table_name)]
        return column_name.lower() in cols
    except Exception:
        return False


def index_exists(conn, table_name: str, index_name: str) -> bool:
    try:
        names = [i["name"].lower() for i in inspect(conn).get_indexes(table_name)]
        return index_name.lower() in names
    except Exception:
        return False


def get_column_type(conn, table_name: str, column_name: str) -> str | None:
    """Return the SQLAlchemy type class name in lowercase, e.g. 'longtext', 'clob', 'varchar'."""
    try:
        for c in inspect(conn).get_columns(table_name):
            if c["name"].lower() == column_name.lower():
                return type(c["type"]).__name__.lower()
        return None
    except Exception:
        return None


def is_column_nullable(conn, table_name: str, column_name: str) -> bool:
    try:
        for c in inspect(conn).get_columns(table_name):
            if c["name"].lower() == column_name.lower():
                return bool(c.get("nullable", False))
        return False
    except Exception:
        return False


def constraint_exists(conn, table_name: str, constraint_name: str) -> bool:
    try:
        uqs = inspect(conn).get_unique_constraints(table_name)
        return any(c["name"] == constraint_name for c in uqs)
    except Exception:
        return False


def get_indexes_for_column(conn, table_name: str, column_name: str) -> list[dict]:
    """Return all indexes on table_name that include column_name."""
    try:
        return [
            i for i in inspect(conn).get_indexes(table_name)
            if column_name in i.get("column_names", [])
        ]
    except Exception:
        return []


def name_sort_clauses(dialect_name: str, col: str = "name") -> list:
    """Return ORDER BY text clauses for locale-aware name sorting.

    Sorts English names before CJK, then applies locale-aware collation.
    MySQL uses REGEXP + CONVERT(... USING gbk); DM8 uses REGEXP_LIKE + NLSSORT.
    """
    from sqlalchemy import text as _text
    if dialect_name == "dm":
        return [
            _text(f"CASE WHEN REGEXP_LIKE({col}, '^[a-zA-Z]') THEN 0 ELSE 1 END"),
            _text(f"NLSSORT({col}, 'NLS_SORT=SCHINESE_PINYIN_M') ASC"),
        ]
    return [
        _text(f'CASE WHEN {col} REGEXP "^[a-zA-Z]" THEN 0 ELSE 1 END'),
        _text(f"CONVERT({col} USING gbk) ASC"),
    ]


def get_version_num_length(conn) -> int | None:
    """Return the character length of alembic_version.version_num, or None."""
    try:
        for c in inspect(conn).get_columns("alembic_version"):
            if c["name"].lower() == "version_num":
                return getattr(c["type"], "length", None)
        return None
    except Exception:
        return None


def update_time_server_default(conn) -> sa.sql.expression.TextClause:
    """Return appropriate server_default for update_time columns.

    MySQL: CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP (native auto-update).
    DaMeng: CURRENT_TIMESTAMP only — triggers handle the ON UPDATE behaviour.
    """
    if get_dialect_name(conn) == "dm":
        return sa.text("CURRENT_TIMESTAMP")
    return sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
