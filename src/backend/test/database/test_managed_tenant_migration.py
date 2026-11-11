"""F009 four-column migration: idempotent DDL, defaults, no table/data repair."""

import importlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, select


def test_upgrade_is_idempotent_and_downgrade_retains_existing_rows():
    migration = importlib.import_module("bisheng.core.database.alembic.versions.v3_1_0_f009_managed_tenant")
    metadata = MetaData()
    tables = {
        name: Table(name, metadata, Column("id", Integer, primary_key=True))
        for name in ("flow", "t_gpts_tools_type", "knowledge")
    }
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            metadata.create_all(connection)
            for table in tables.values():
                connection.execute(table.insert().values(id=7))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
                assert set(inspect(connection).get_table_names()) == set(tables)
                upgraded = MetaData()
                upgraded.reflect(connection)
                for name in ("flow", "t_gpts_tools_type"):
                    row = connection.execute(select(upgraded.tables[name])).one()._mapping
                    assert row["id"] == 7 and row["creation_state"] == "READY"
                copy = connection.execute(select(upgraded.tables["knowledge"])).one()._mapping
                assert copy["copy_source_id"] is None and copy["copy_target_id"] is None
                migration.downgrade()
                for name, table in tables.items():
                    assert {column["name"] for column in inspect(connection).get_columns(name)} == {"id"}
                    assert connection.execute(select(table.c.id)).scalar_one() == 7
    finally:
        engine.dispose()
