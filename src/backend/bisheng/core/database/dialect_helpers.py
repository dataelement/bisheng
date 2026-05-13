"""Dialect-agnostic helpers for DaMeng + MySQL dual-database support."""
from __future__ import annotations

import json as _json

import sqlalchemy as sa
from sqlalchemy import inspect, Text, CLOB, JSON
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import FunctionElement
from sqlalchemy.types import TypeDecorator


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
