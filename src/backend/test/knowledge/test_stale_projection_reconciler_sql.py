"""The stale-projection reconciler has to run on DaMeng as well as MySQL.

It was raw SQL written for MySQL: `CAST(kf.id AS CHAR)` means CHAR(1) on
DaMeng, so every multi-digit id was truncated and the statement died with
`[CODE:-6149] Data lose`. The task fired every 10 minutes and failed on its
first query every time, so nothing was ever repaired — which is how a file
whose permission mirror still pointed at its old folder stayed unfixable, and
undeletable, for as long as it did. `SUBSTRING_INDEX` is MySQL-only too.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import mysql, sqlite

from bisheng.knowledge.domain.services.stale_projection_reconciler import (
    _compute_correct_parent,
    _mismatch_query,
)

# Functions with no DaMeng equivalent, wherever they are emitted.
_MYSQL_ONLY = ("SUBSTRING_INDEX", "GROUP_CONCAT", "IFNULL")


def _sql(dialect, *, nested: bool) -> str:
    return str(
        _mismatch_query(batch_limit=200, nested=nested).compile(
            dialect=dialect,
            compile_kwargs={"literal_binds": True},
        )
    )


@pytest.mark.parametrize("nested", [False, True], ids=["root", "nested"])
def test_the_query_compiles_for_a_non_mysql_dialect(nested):
    """Compiling anywhere but MySQL is what the raw version could not do."""
    sql = _sql(sqlite.dialect(), nested=nested)
    assert "resource_permission_mode" in sql
    assert "knowledgefile" in sql


@pytest.mark.parametrize("nested", [False, True], ids=["root", "nested"])
@pytest.mark.parametrize("dialect", [mysql.dialect(), sqlite.dialect()], ids=["mysql", "sqlite"])
def test_no_mysql_only_function_survives(dialect, nested):
    sql = _sql(dialect, nested=nested).upper()
    for token in _MYSQL_ONLY:
        assert token not in sql, f"{token} is not portable"


@pytest.mark.parametrize("nested", [False, True], ids=["root", "nested"])
def test_the_cast_is_dialect_aware(nested):
    """`CAST(x AS CHAR)` is CHAR(1) on DaMeng — every id truncated, statement dead.

    It is right on MySQL, which is why the cast must come from the shared
    helper and be compiled per dialect rather than written into the text.
    """
    assert "AS CHAR" in _sql(mysql.dialect(), nested=nested).upper()
    assert "AS CHAR" not in _sql(sqlite.dialect(), nested=nested).upper()


def test_the_root_query_asks_for_files_with_no_path():
    sql = _sql(sqlite.dialect(), nested=False)
    assert "file_level_path IS NOT NULL" in sql
    assert "knowledge_space" in sql


def test_the_nested_query_matches_the_last_path_segment_without_substring_index():
    sql = _sql(sqlite.dialect(), nested=True)
    # The portable stand-in: the whole path equals the parent, or ends in "/<parent>".
    assert "LIKE" in sql.upper()
    assert "'folder'" in sql


@pytest.mark.parametrize(
    ("path", "knowledge_id", "expected"),
    [
        ("", 152, ("knowledge_space", "152")),
        (None, 152, ("knowledge_space", "152")),
        ("/1110/", 152, ("folder", "1110")),
        ("1110", 152, ("folder", "1110")),
        ("/1110/1111/", 152, ("folder", "1111")),
    ],
)
def test_the_business_truth_parent_comes_from_the_path(path, knowledge_id, expected):
    assert _compute_correct_parent(path, knowledge_id) == expected
