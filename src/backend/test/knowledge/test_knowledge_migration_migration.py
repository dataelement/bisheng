from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from bisheng.core.config.settings import CeleryConf
from bisheng.core.database.alembic.versions import (
    v2_6_0_f075_knowledge_file_migration as migration,
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
        "schedule": 60.0,
    }
