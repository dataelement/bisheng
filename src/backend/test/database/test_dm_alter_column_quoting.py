"""The DaMeng MODIFY DDL must quote the table, not only the column.

DM8 has no `ALTER TABLE t ALTER COLUMN c TYPE x`, so env.py hand-builds
`ALTER TABLE t MODIFY c newtype`. It quoted the column and left the table bare,
which is fine until the table is named `user` — a DM8 reserved word. F056 then
failed with `-2007 ... nearby [user]`, and since entrypoint.sh only warns when a
migration fails, the deployment came up serving the old schema instead of
stopping.
"""

from types import SimpleNamespace

import pytest

from bisheng.core.database.alembic_helpers.dm_ddl import build_modify_column_ddl

# Quote what a real preparer would quote: reserved words, nothing else.
_RESERVED = {"user", "order", "session"}
_PREPARER = SimpleNamespace(quote=lambda name: f'"{name}"' if name in _RESERVED else name)


def test_reserved_table_name_is_quoted():
    stmt = build_modify_column_ddl(_PREPARER, "user", "user_name", "VARCHAR2(128 CHAR)")
    assert stmt == 'ALTER TABLE "user" MODIFY user_name VARCHAR2(128 CHAR)'


def test_ordinary_table_name_is_left_bare():
    stmt = build_modify_column_ddl(_PREPARER, "knowledge", "name", "VARCHAR2(64 CHAR)")
    assert stmt == "ALTER TABLE knowledge MODIFY name VARCHAR2(64 CHAR)"


def test_reserved_column_name_is_still_quoted():
    stmt = build_modify_column_ddl(_PREPARER, "knowledge", "user", "VARCHAR2(64 CHAR)")
    assert stmt == 'ALTER TABLE knowledge MODIFY "user" VARCHAR2(64 CHAR)'


@pytest.mark.parametrize("schema", ["BISHENG_105"])
def test_schema_is_prefixed(schema):
    stmt = build_modify_column_ddl(_PREPARER, "user", "user_name", "VARCHAR2(128 CHAR)", schema)
    assert stmt == f'ALTER TABLE {schema}."user" MODIFY user_name VARCHAR2(128 CHAR)'


def test_every_f056_column_survives_the_reserved_table():
    """F056 alters seven columns on `user`; none may emit an unquoted table."""
    for column in ("user_name", "email", "phone_number", "dept_id", "remark", "avatar", "password"):
        stmt = build_modify_column_ddl(_PREPARER, "user", column, "VARCHAR2(255 CHAR)")
        assert stmt.startswith('ALTER TABLE "user" MODIFY '), stmt
