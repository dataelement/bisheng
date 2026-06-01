"""T006 — Keyset WHERE helper unit tests (AC-03, AC-05)."""
from __future__ import annotations

import pytest

from sqlalchemy import Column, Integer, MetaData, String, Table, case, func, select
from sqlalchemy.dialects import mysql

from bisheng.database.utils.keyset import build_keyset_where


@pytest.fixture
def kf_table() -> Table:
    """Mirror the keyset-relevant columns of ``knowledge_file``."""
    metadata = MetaData()
    return Table(
        "knowledge_file",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("file_type", Integer),
        Column("file_name", String(255)),
    )


def _compile_sql(stmt) -> str:
    return str(
        stmt.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


# ---------------------------------------------------------------------------
# Happy path: 1 / 2 / 3 column keysets
# ---------------------------------------------------------------------------


def test_single_column_keyset(kf_table):
    stmt = select(kf_table).where(
        build_keyset_where(
            sort_cols=(kf_table.c.id,),
            cursor_values=(42,),
        )
    )
    sql = _compile_sql(stmt)
    # tuple_() over single column may emit `(col) > (val)` or `col > val`;
    # both are valid.
    assert "knowledge_file.id" in sql
    assert "42" in sql
    assert ">" in sql


def test_two_column_keyset(kf_table):
    """Expanded OR ladder: file_name > v0  OR  (file_name = v0 AND id > v1).
    Row-value tuple form removed for DM8 compatibility (see _USE_EXPANDED_FALLBACK)."""
    stmt = select(kf_table).where(
        build_keyset_where(
            sort_cols=(kf_table.c.file_name, kf_table.c.id),
            cursor_values=("report.pdf", 100),
        )
    )
    sql = _compile_sql(stmt)
    assert "knowledge_file.file_name > 'report.pdf'" in sql
    assert "knowledge_file.file_name = 'report.pdf'" in sql
    assert "knowledge_file.id > 100" in sql
    assert sql.count("OR") >= 1


def test_three_column_keyset(kf_table):
    """Expanded OR ladder with three branches."""
    stmt = select(kf_table).where(
        build_keyset_where(
            sort_cols=(kf_table.c.file_type, kf_table.c.file_name, kf_table.c.id),
            cursor_values=(0, "report.pdf", 9876),
        )
    )
    sql = _compile_sql(stmt)
    assert "knowledge_file.file_type > 0" in sql
    assert "knowledge_file.file_type = 0" in sql
    assert "knowledge_file.file_name > 'report.pdf'" in sql
    assert "knowledge_file.id > 9876" in sql
    assert sql.count("OR") >= 2


# ---------------------------------------------------------------------------
# AD-14 / spec §7.3: case() expression as sort_col (ext_rank for knowledge_file)
# ---------------------------------------------------------------------------


def test_keyset_supports_case_expression_as_sort_col(kf_table):
    """ext_rank is a 15-WHEN CASE expression; helper must accept it as sort_col."""
    ext_rank_expr = case(
        (func.lower(kf_table.c.file_name).like("%.pdf"), 1),
        (func.lower(kf_table.c.file_name).like("%.docx"), 2),
        (func.lower(kf_table.c.file_name).like("%.doc"), 3),
        else_=99,
    )

    stmt = select(kf_table).where(
        build_keyset_where(
            sort_cols=(ext_rank_expr, kf_table.c.file_name, kf_table.c.id),
            cursor_values=(1, "report.pdf", 9876),
        )
    )

    sql = _compile_sql(stmt)
    # The CASE WHEN expression should be inlined into the expanded OR ladder.
    # Note: MySQL dialect escapes literal % as %% in LIKE patterns when binding.
    assert "CASE" in sql
    assert "WHEN (lower(knowledge_file.file_name) LIKE '%%.pdf')" in sql
    assert "THEN 1" in sql and "THEN 2" in sql and "THEN 3" in sql and "ELSE 99 END" in sql
    # Expanded form: cursor value 1 appears as the ext_rank comparator literal.
    assert "> 1" in sql
    assert "knowledge_file.file_name > 'report.pdf'" in sql
    assert "knowledge_file.id > 9876" in sql


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_raises_when_lengths_mismatch(kf_table):
    with pytest.raises(ValueError, match="length mismatch"):
        build_keyset_where(
            sort_cols=(kf_table.c.file_name, kf_table.c.id),
            cursor_values=("only_one_value",),
        )


# ---------------------------------------------------------------------------
# Fallback path (currently disabled; sanity-test the function directly)
# ---------------------------------------------------------------------------


def test_mixed_direction_uses_expanded_form(kf_table):
    """F027 knowledge_file: file_type ASC, update_time DESC, id DESC — mixed
    direction must fall back to expanded OR form because tuple_() can't
    express per-column direction."""
    where = build_keyset_where(
        sort_cols=(kf_table.c.file_type, kf_table.c.file_name, kf_table.c.id),
        cursor_values=(1, "report.pdf", 9876),
        descending=(False, True, True),  # file_type ASC, others DESC
    )
    sql = str(where.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))

    # ASC col uses > ; DESC cols use <
    assert "knowledge_file.file_type > 1" in sql
    assert "knowledge_file.file_name < 'report.pdf'" in sql
    assert "knowledge_file.id < 9876" in sql
    # Mixed-direction always expands to OR ladder, not tuple comparison
    assert sql.count("OR") >= 2


def test_mixed_direction_length_mismatch_raises(kf_table):
    with pytest.raises(ValueError, match="descending sequence length mismatch"):
        build_keyset_where(
            sort_cols=(kf_table.c.file_type, kf_table.c.file_name, kf_table.c.id),
            cursor_values=(1, "report.pdf", 9876),
            descending=(False, True),  # length 2 vs 3 cols → error
        )


def test_expanded_fallback_emits_nested_or(kf_table):
    """If a future dialect rejects tuple_() we'll flip _USE_EXPANDED_FALLBACK;
    smoke-test the fallback function directly so it stays exercised."""
    from bisheng.database.utils.keyset import _expanded_keyset_where

    where = _expanded_keyset_where(
        sort_cols=(kf_table.c.file_type, kf_table.c.file_name, kf_table.c.id),
        cursor_values=(0, "report.pdf", 9876),
    )
    sql = str(where.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))

    # Three OR branches: a > a0  OR  (a = a0 AND b > b0)  OR  (a = a0 AND b = b0 AND id > id0)
    assert sql.count("OR") >= 2
    assert "knowledge_file.file_type > 0" in sql
    assert "knowledge_file.file_type = 0" in sql
    assert "knowledge_file.id > 9876" in sql
