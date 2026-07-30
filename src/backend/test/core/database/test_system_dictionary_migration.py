"""Regression tests for the F072 system dictionary migration."""

import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_MODULE = "bisheng.core.database.alembic.versions.v2_6_0_f072_add_system_dictionary"


def _run_upgrade(connection: sa.Connection) -> None:
    migration = importlib.import_module(MIGRATION_MODULE)
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        migration.upgrade()


def _expected_seed_count() -> int:
    migration = importlib.import_module(MIGRATION_MODULE)
    return sum(len(values) for values in migration._INITIAL_VALUES.values())


def test_upgrade_seeds_system_dictionary_and_is_idempotent() -> None:
    engine = sa.create_engine("sqlite://")

    with engine.begin() as connection:
        _run_upgrade(connection)
        first_count = connection.scalar(sa.text("SELECT COUNT(*) FROM system_dictionary"))

        _run_upgrade(connection)
        second_count = connection.scalar(sa.text("SELECT COUNT(*) FROM system_dictionary"))

    assert first_count == _expected_seed_count()
    assert second_count == first_count


def test_upgrade_recovers_from_partially_seeded_table() -> None:
    engine = sa.create_engine("sqlite://")

    with engine.begin() as connection:
        _run_upgrade(connection)
        connection.execute(
            sa.text(
                """
                DELETE FROM system_dictionary
                WHERE tenant_id = 1
                  AND type = 'expert_position'
                  AND dict_key = 'expert_position_001'
                """
            )
        )

        _run_upgrade(connection)

        count = connection.scalar(sa.text("SELECT COUNT(*) FROM system_dictionary"))
        restored = connection.scalar(
            sa.text(
                """
                SELECT COUNT(*)
                FROM system_dictionary
                WHERE tenant_id = 1
                  AND type = 'expert_position'
                  AND dict_key = 'expert_position_001'
                """
            )
        )

    assert count == _expected_seed_count()
    assert restored == 1
