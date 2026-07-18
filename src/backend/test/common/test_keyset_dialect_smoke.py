"""T001 — DM8 + MySQL `tuple_()` keyset dialect smoke test.

Verifies AD-13 main path: SQLAlchemy `tuple_(a, b, id) > tuple_(a0, b0, id0)`
compiles to valid keyset-comparison SQL on MySQL, DM (stub), and SQLite dialects
without raising. If any dialect rejects the tuple form, T006 must implement
the fallback expanded form (`a > a0 OR (a=a0 AND b > b0) OR ...`).

Pattern follows F025 `test_approval_dialect_compat.py` — no real DB connection
required; we compile against dialect classes and inspect generated SQL.
"""
from __future__ import annotations

import pytest

from sqlalchemy import Column, Integer, MetaData, String, Table, select, tuple_
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.engine.default import DefaultDialect


class _DmDialect(DefaultDialect):
    """Stub DM (达梦) dialect inheriting DefaultDialect.

    DM8 is largely SQL-92 / Oracle compatible; row-value (tuple) comparison
    `(a, b, id) > (a0, b0, id0)` is SQL standard and supported.
    """

    name = "dm"


@pytest.fixture
def knowledge_file_table() -> Table:
    """Mirror the keyset-relevant columns of `knowledge_file` from spec §6.2."""
    metadata = MetaData()
    return Table(
        "knowledge_file",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("file_type", Integer),
        Column("file_name", String(255)),
    )


def _build_keyset_where(table: Table, cursor_values: tuple):
    """Construct `WHERE (file_type, file_name, id) > (v0, v1, v2)` via tuple_().

    This is the prototype of the T006 helper `_build_keyset_where` main path.
    """
    sort_cols = (table.c.file_type, table.c.file_name, table.c.id)
    return tuple_(*sort_cols) > tuple_(*cursor_values)


# ---------------------------------------------------------------------------
# Main path: tuple_() compiles successfully on all three dialects
# ---------------------------------------------------------------------------


def test_tuple_keyset_compiles_on_mysql_dialect(knowledge_file_table):
    stmt = (
        select(knowledge_file_table)
        .where(_build_keyset_where(knowledge_file_table, (0, "report.pdf", 9876)))
        .limit(100)
    )

    sql = str(
        stmt.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "(knowledge_file.file_type, knowledge_file.file_name, knowledge_file.id) > (0," in sql
    assert "report.pdf" in sql
    assert "9876" in sql
    assert "LIMIT 100" in sql


def test_tuple_keyset_compiles_on_dm_dialect(knowledge_file_table):
    stmt = (
        select(knowledge_file_table)
        .where(_build_keyset_where(knowledge_file_table, (0, "report.pdf", 9876)))
        .limit(100)
    )

    sql = str(
        stmt.compile(
            dialect=_DmDialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    # DM falls back to DefaultDialect tuple emission — standard SQL row comparison.
    assert "(knowledge_file.file_type, knowledge_file.file_name, knowledge_file.id) > (0," in sql
    assert "report.pdf" in sql
    assert "9876" in sql


def test_tuple_keyset_compiles_on_sqlite_dialect(knowledge_file_table):
    """SQLite is the unit-test substrate; must work for service-layer pytest."""
    stmt = (
        select(knowledge_file_table)
        .where(_build_keyset_where(knowledge_file_table, (0, "report.pdf", 9876)))
        .limit(100)
    )

    sql = str(
        stmt.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "(knowledge_file.file_type, knowledge_file.file_name, knowledge_file.id) > (0," in sql
    assert "report.pdf" in sql
    assert "9876" in sql


# ---------------------------------------------------------------------------
# Boundary conditions
# ---------------------------------------------------------------------------


def test_tuple_keyset_supports_two_columns(knowledge_file_table):
    """Knowledge / Flow lists use 2-column sort keys `(update_time, id)`."""
    sort_cols = (knowledge_file_table.c.file_name, knowledge_file_table.c.id)
    where = tuple_(*sort_cols) > tuple_("a.pdf", 100)
    stmt = select(knowledge_file_table).where(where).limit(20)

    sql = str(stmt.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "(knowledge_file.file_name, knowledge_file.id) > ('a.pdf', 100)" in sql


def test_tuple_keyset_supports_single_column(knowledge_file_table):
    """Degenerate single-column case — should still work."""
    where = tuple_(knowledge_file_table.c.id) > tuple_(42)
    stmt = select(knowledge_file_table).where(where).limit(20)

    sql = str(stmt.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
    # single-col tuple_ on MySQL emits `(col) > (val)` or `col > val` depending on version.
    # Both forms are valid; we just assert the comparison appears.
    assert "knowledge_file.id" in sql and "42" in sql and ">" in sql
