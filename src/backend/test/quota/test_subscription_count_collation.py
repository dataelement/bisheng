"""The actual quota queries must join text IDs across database collations."""

import pytest
from sqlalchemy.dialects import mysql, sqlite

from bisheng.role.domain.repositories.quota_repository import usage_statement

METRICS = [("channel_subscribe", "channel"), ("knowledge_space_subscribe", "knowledge")]


@pytest.mark.parametrize("resource_type,parent", METRICS)
@pytest.mark.parametrize("user_id", [None, 77])
def test_mysql_subscription_join_has_explicit_collation(resource_type, parent, user_id):
    statement = usage_statement(resource_type, 2, user_id=user_id)
    sql = str(statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
    assert f"CAST({parent}.id AS CHAR) COLLATE utf8mb4_unicode_ci = space_channel_member.business_id" in sql
    assert f"{parent}.tenant_id IN (" in sql
    if user_id is not None:
        assert "space_channel_member.user_id = 77" in sql
    else:
        assert "space_channel_member.user_id =" not in sql


@pytest.mark.parametrize("resource_type,parent", METRICS)
@pytest.mark.parametrize("dialect_name", ["sqlite", "dm"])
def test_non_mysql_subscription_join_has_no_mysql_collation(resource_type, parent, dialect_name):
    dialect = sqlite.dialect() if dialect_name == "sqlite" else pytest.importorskip("dmSQLAlchemy.dmpython").dialect()
    sql = str(usage_statement(resource_type, 2, user_id=77).compile(dialect=dialect))
    assert "CAST(" in sql and "COLLATE" not in sql
    assert f"{parent}.id" in sql.lower() and "business_id" in sql.lower()
