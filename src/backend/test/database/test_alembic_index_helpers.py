from unittest.mock import MagicMock, patch

from alembic.ddl.impl import DefaultImpl
from alembic.ddl.mysql import MySQLImpl
from sqlalchemy import Column, Index, Integer, MetaData, Table, UniqueConstraint, create_engine
from sqlalchemy.dialects import mysql

from bisheng.core.database.alembic_helpers import mysql_impl
from bisheng.core.database.alembic_helpers.indexes import find_equivalent_index
from bisheng.core.database.alembic_helpers.mysql_impl import BishengMySQLImpl


def test_finds_same_non_unique_columns_with_different_name():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    table = Table("items", metadata, Column("tenant_id", Integer))
    Index("ix_items_tenant_id", table.c.tenant_id)

    with engine.connect() as connection:
        metadata.create_all(connection)
        candidate = Index("idx_items_tenant_id", table.c.tenant_id)

        assert find_equivalent_index(connection, candidate) == (True, "ix_items_tenant_id")


def test_does_not_match_different_column_order():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    table = Table(
        "items",
        metadata,
        Column("tenant_id", Integer),
        Column("created_at", Integer),
    )
    Index("ix_items_tenant_created", table.c.tenant_id, table.c.created_at)

    with engine.connect() as connection:
        metadata.create_all(connection)
        candidate = Index("idx_items_created_tenant", table.c.created_at, table.c.tenant_id)

        assert find_equivalent_index(connection, candidate) == (False, None)


def test_does_not_match_different_uniqueness():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    table = Table("items", metadata, Column("tenant_id", Integer))
    Index("ix_items_tenant_id", table.c.tenant_id)

    with engine.connect() as connection:
        metadata.create_all(connection)
        candidate = Index("uk_items_tenant_id", table.c.tenant_id, unique=True)

        assert find_equivalent_index(connection, candidate) == (False, None)


def test_finds_equivalent_unique_constraint():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    table = Table(
        "items",
        metadata,
        Column("tenant_id", Integer),
        UniqueConstraint("tenant_id", name="uk_items_tenant_id"),
    )

    with engine.connect() as connection:
        metadata.create_all(connection)
        candidate = Index("ux_items_tenant_id", table.c.tenant_id, unique=True)

        assert find_equivalent_index(connection, candidate) == (True, "uk_items_tenant_id")


def test_bisheng_mysql_impl_is_registered():
    assert DefaultImpl.get_by_dialect(mysql.dialect()) is BishengMySQLImpl


def test_bisheng_mysql_impl_skips_equivalent_index():
    metadata = MetaData()
    table = Table("items", metadata, Column("tenant_id", Integer))
    candidate = Index("idx_items_tenant_id", table.c.tenant_id)
    implementation = BishengMySQLImpl(
        mysql.dialect(),
        MagicMock(),
        as_sql=False,
        transactional_ddl=None,
        output_buffer=None,
        context_opts={},
    )

    with (
        patch.object(mysql_impl, "find_equivalent_index", return_value=(True, "ix_items_tenant_id")),
        patch.object(MySQLImpl, "create_index") as default_create_index,
    ):
        assert implementation.create_index(candidate) is None

    default_create_index.assert_not_called()
