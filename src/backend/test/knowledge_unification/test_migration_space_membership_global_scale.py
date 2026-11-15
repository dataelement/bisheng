"""T997: bounded PK pages and exact indexed numeric parents, without CAST."""

import math
import re

import pytest
from sqlalchemy.dialects import mysql
from test.knowledge_unification.test_migration_space_membership_global import Member, member, run
from test.knowledge_unification.test_migration_space_membership_global import control_native as control_native
from test.knowledge_unification.test_migration_space_membership_global import native as native

from bisheng.knowledge.domain.models.knowledge import Knowledge


@pytest.mark.parametrize("count", [401, 10001])
async def test_global_space_cost_is_two_indexed_queries_per_member_page(native, count):
    await native.insert(
        Knowledge,
        [{"id": i + 10, "tenant_id": 101 if i % 2 else 202, "type": i % 4, "name": str(i)} for i in range(count)],
    )
    await native.insert(
        Member, [member(2 * i + 2, str(i + 10), status=("ACTIVE", "PENDING", "REJECTED")[i % 3]) for i in range(count)]
    )
    native.queries.clear()
    native.statements.clear()
    native.writes.clear()
    assert await run(native, control=True) is None
    pages = math.ceil(count / 200)
    members = [(sql, params) for sql, params in native.queries if "FROM space_channel_member" in sql]
    roots = [(sql, params) for sql, params in native.queries if "FROM knowledge" in sql]
    assert len(members) == len(roots) == pages
    assert len(native.queries) == 2 + 2 * pages
    assert all("LIMIT" in sql and params[-2:] == (201, 0) for sql, params in members)
    assert all("LEFT OUTER JOIN tenant" in sql and "space_channel_member" not in sql for sql, _ in roots)
    assert all(1 <= len(params) <= 200 and all(type(value) is int for value in params) for _, params in roots)
    assert {value for _, params in roots for value in params} == set(range(10, 10 + count))
    for statement in native.statements:
        for dialect in (None, mysql.dialect()):
            sql = str(statement.compile(dialect=dialect)).upper()
            assert "CAST(" not in sql and "CROSS JOIN" not in sql
            assert not re.search(r"\bFROM\s+[^\n]+,", sql)
    assert not native.writes
    print(
        {
            "members": count,
            "member_pages": len(members),
            "numeric_root_pages": len(roots),
            "total_selects": len(native.queries),
            "max_root_params": max(len(params) for _, params in roots),
        }
    )
