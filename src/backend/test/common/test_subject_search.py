"""Subject identities are literal prefixes, not numeric coercions or wildcards."""

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, select
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.default import DefaultDialect

from bisheng.common.subject_search import normalize_keyword, numeric_prefix_ranges
from bisheng.core.database.subject_search import (
    case_sensitive_prefix,
    exact_id_priority,
    numeric_id_priority,
    numeric_subject_match_condition,
    subject_match_condition,
)


def test_normalization_and_codepoint_limit():
    assert normalize_keyword("\u0085  jia\r\n0100 \u3000") == "jia 0100"
    assert normalize_keyword("😀" * 255) == "😀" * 255
    with pytest.raises(ValueError):
        normalize_keyword("😀" * 256)


def test_numeric_prefixes_keep_canonical_display():
    assert numeric_prefix_ranges("01") == []
    assert numeric_prefix_ranges("\uff11\uff12") == []
    assert numeric_prefix_ranges("2147483648") == []
    assert numeric_prefix_ranges("12", 1300) == [(12, 12), (120, 129), (1200, 1299)]
    assert numeric_prefix_ranges("0", 1300) == [(0, 0)]


@pytest.fixture()
def subjects():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    users = Table(
        "people", metadata, Column("id", Integer, primary_key=True), Column("name", String), Column("ext", String)
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            users.insert(),
            [
                {"id": 1, "name": "same", "ext": "jia0100"},
                {"id": 2, "name": "same", "ext": "jia0100-02"},
                {"id": 3, "name": "jia0100", "ext": "jia0100"},
                {"id": 4, "name": "other", "ext": "jia_04"},
                {"id": 5, "name": "other", "ext": "jia%05"},
                {"id": 6, "name": "other", "ext": None},
                {"id": 12, "name": "other", "ext": "0012"},
                {"id": 120, "name": "other", "ext": "test"},
            ],
        )
    yield engine, users
    engine.dispose()


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("jia", [1, 2, 3, 4, 5]),
        ("0100", []),
        ("JIA", [3]),
        ("jia_", [4]),
        ("jia%", [5]),
        ("00", [12]),
    ],
)
def test_literal_case_sensitive_identity_prefix(subjects, query, expected):
    engine, users = subjects
    with engine.connect() as conn:
        predicate = subject_match_condition(users.c.id, users.c.name, users.c.ext, query, name_prefix=True)
        assert list(conn.scalars(select(users.c.id).where(predicate).order_by(users.c.id))) == expected


def test_exact_priority_dedup_and_page_before_id_order(subjects):
    engine, users = subjects
    predicate = subject_match_condition(users.c.id, users.c.name, users.c.ext, "jia0100", name_prefix=True)
    stmt = select(users.c.id).where(predicate).order_by(exact_id_priority(users.c.ext, "jia0100"), users.c.id.desc())
    with engine.connect() as conn:
        assert list(conn.scalars(stmt)) == [3, 1, 2]
        assert list(conn.scalars(stmt.limit(1).offset(1))) == [1]


def test_numeric_group_prefix_uses_ranges(subjects):
    engine, groups = subjects
    predicate = numeric_subject_match_condition(groups.c.id, groups.c.name, "12")
    with engine.connect() as conn:
        stmt = select(groups.c.id).where(predicate).order_by(numeric_id_priority(groups.c.id, "12"), groups.c.id.desc())
        assert list(conn.scalars(stmt)) == [12, 120]


def test_statement_cache_does_not_reuse_previous_prefix(subjects):
    engine, users = subjects
    with engine.connect() as conn:
        for query, expected in [("jia_", [4]), ("jia%", [5]), ("00", [12])]:
            assert list(conn.scalars(select(users.c.id).where(case_sensitive_prefix(users.c.ext, query)))) == expected


def test_mysql_and_dm_compile_index_range_and_binary_residual(subjects):
    _, users = subjects
    stmt = select(users.c.id).where(case_sensitive_prefix(users.c.ext, "jia_"))
    mysql_sql = str(stmt.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "CAST(people.ext AS BINARY)" in mysql_sql
    assert "people.ext LIKE" in mysql_sql
    dm = DefaultDialect()
    dm.name = "dm"
    dm_sql = str(stmt.compile(dialect=dm, compile_kwargs={"literal_binds": True}))
    assert "BINARY people.ext LIKE" in dm_sql
    assert "people.ext LIKE" in dm_sql


def test_id_branch_itself_is_case_sensitive(subjects):
    engine, users = subjects
    with engine.connect() as conn:
        assert list(conn.scalars(select(users.c.id).where(case_sensitive_prefix(users.c.ext, "JIA")))) == []
