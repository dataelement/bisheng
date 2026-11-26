"""The phase DDL preserves old cleanup rows and accepts model-created tables."""

import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_delete_phase_upgrade_is_neutral_and_idempotent():
    revision = importlib.import_module(
        "bisheng.core.database.alembic.versions.v3_1_0_beta1_f118_knowledge_deletion_execution"
    )
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    old = sa.Table(
        "knowledge_space_delete_job",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("space_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("manifest", sa.Text(), nullable=False),
    )
    original = '{"original":"preserve unchanged","file_ids":[31]}'
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(
            old.insert(), {"id": "old-job", "tenant_id": 101, "space_id": 1, "state": "PENDING", "manifest": original}
        )
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()
            revision.upgrade()
        table = sa.Table(old.name, sa.MetaData(), autoload_with=connection)
        row = connection.execute(table.select()).mappings().one()
        assert dict(row) == {
            "id": "old-job",
            "tenant_id": 101,
            "space_id": 1,
            "state": "PENDING",
            "manifest": original,
            "operation_type": None,
            "business_phase": None,
        }
        indexes = sa.inspect(connection).get_indexes(old.name)
        assert [item["column_names"] for item in indexes if item["name"] == "ix_space_delete_scope"] == [
            ["tenant_id", "space_id", "operation_type", "business_phase", "state"]
        ]
        assert table.c.operation_type.nullable and table.c.business_phase.nullable
    engine.dispose()
