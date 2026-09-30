from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from bisheng.core.config.settings import CeleryConf
from bisheng.core.database.alembic.versions import (
    v2_6_0_f075_knowledge_file_migration as migration,
)
from bisheng.core.database.alembic.versions import (
    v2_6_0_f107_migration_reconcile_budget as recovery_migration,
)


def test_migration_upgrade_is_idempotent_and_downgrade_removes_child_tables_first():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()

        inspector = inspect(connection)
        assert {
            "knowledge_migration_batch",
            "knowledge_migration_unit",
            "knowledge_migration_file",
            "knowledge_migration_attempt",
        }.issubset(set(inspector.get_table_names()))
        assert {
            "uk_knowledge_migration_batch_no",
            "uk_knowledge_migration_request",
        } == {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("knowledge_migration_batch")
        }
        assert "ix_kmu_batch_round_status" in {
            index["name"] for index in inspector.get_indexes("knowledge_migration_unit")
        }

        migration.downgrade()
        assert not {
            "knowledge_migration_batch",
            "knowledge_migration_unit",
            "knowledge_migration_file",
            "knowledge_migration_attempt",
        }.intersection(set(inspect(connection).get_table_names()))


def test_migration_reconcile_is_registered_in_default_beat_schedule():
    celery_conf = CeleryConf()

    assert celery_conf.beat_schedule["reconcile_knowledge_migrations"] == {
        "task": "bisheng.worker.knowledge.file_migration.reconcile",
        "schedule": 300.0,
    }


def test_migration_reconcile_preserves_explicit_schedule():
    entry = {"task": "bisheng.worker.knowledge.file_migration.reconcile", "schedule": 900.0}
    assert CeleryConf(beat_schedule={"reconcile_knowledge_migrations": entry}).beat_schedule[
        "reconcile_knowledge_migrations"
    ] == entry


def test_recovery_budget_migration_is_additive_and_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        migration.op = recovery_migration.op = operations
        migration.upgrade()
        recovery_migration.upgrade()
        recovery_migration.upgrade()
        columns = {column["name"]: column for column in inspect(connection).get_columns("knowledge_migration_batch")}
        assert columns["reconcile_count"]["default"] == "0"
        assert columns["next_reconcile_at"]["nullable"]
        recovery_migration.downgrade()
        recovery_migration.downgrade()
        assert "reconcile_count" not in {
            column["name"] for column in inspect(connection).get_columns("knowledge_migration_batch")
        }
