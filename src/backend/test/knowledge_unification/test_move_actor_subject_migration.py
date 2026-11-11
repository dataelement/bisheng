"""Neutral, repeatable subject DDL preserves original task provenance as-is."""

import importlib.util
import re
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt

TABLES = ("knowledge_processing_job", "knowledge_processing_retry_receipt")
SUBJECT_COLUMNS = ("actor_subject_type", "actor_subject_id")
INDEX_COLUMNS = ["tenant_id", "job_id", "actor_subject_id", "actor_subject_type", "accepted_job_revision", "id"]


def migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "bisheng/core/database/alembic/versions/v3_1_0_beta1_f118_move_actor_subject.py"
    )
    spec = importlib.util.spec_from_file_location("f118_move_subject_migration", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_revision_follows_the_actual_previous_single_head():
    value = migration()
    assert value.revision == "f118_move_actor_subject"
    assert value.down_revision == "f118_finalize_retry"
    assert value.branch_labels is value.depends_on is None


@pytest.mark.parametrize("existing", ["none", "columns", "index"])
def test_native_upgrade_repeats_without_changing_or_deriving_old_actor_facts(existing):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()

    def shared():
        return [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.Integer, nullable=False),
            sa.Column("actor_user_id", sa.Integer, nullable=False),
            sa.Column("actor_reference", sa.Text, nullable=False),
        ]

    def subject():
        return [
            sa.Column("actor_subject_type", sa.String(32), nullable=True),
            sa.Column("actor_subject_id", sa.BigInteger, nullable=True),
        ]

    job = sa.Table(
        TABLES[0], metadata, *shared(), sa.Column("kind", sa.String(32)), *(subject() if existing != "none" else [])
    )
    retry = sa.Table(
        TABLES[1],
        metadata,
        *shared(),
        sa.Column("job_id", sa.String(36)),
        sa.Column("accepted_job_revision", sa.Integer),
        *(subject() if existing != "none" else []),
    )
    if existing == "index":
        sa.Index("ix_kpr_job_subject", *(retry.c[name] for name in INDEX_COLUMNS))
    metadata.create_all(engine)
    old_columns = {
        table.name: [column.name for column in table.columns if column.name not in SUBJECT_COLUMNS]
        for table in (job, retry)
    }
    original = '{"actor":{"subject_type":"service_account","subject_id":50},"untouched":"original"}'
    try:
        with engine.begin() as connection:
            connection.execute(
                job.insert(),
                {
                    "id": "original-job",
                    "tenant_id": 101,
                    "actor_user_id": 7,
                    "actor_reference": original,
                    "kind": "move_index",
                },
            )
            connection.execute(
                retry.insert(),
                {
                    "id": "original-retry",
                    "tenant_id": 101,
                    "job_id": "original-job",
                    "actor_user_id": 8,
                    "actor_reference": original,
                    "accepted_job_revision": 3,
                },
            )
        with engine.connect() as connection:
            before = {
                table.name: [
                    tuple(row)
                    for row in connection.execute(sa.select(*(table.c[name] for name in old_columns[table.name])))
                ]
                for table in (job, retry)
            }
            seen = []

            def reject_data_writes(_conn, _cursor, statement, _params, _context, _many):
                seen.append(statement)
                assert not re.match(r"\s*(INSERT|UPDATE|DELETE|REPLACE)\b", statement, re.I), statement

            sa.event.listen(connection, "before_cursor_execute", reject_data_writes)
            with Operations.context(MigrationContext.configure(connection)):
                value = migration()
                value.upgrade()
                value.upgrade()
            migration_statements = tuple(seen)
            reflected = sa.MetaData()
            for name in TABLES:
                table = sa.Table(name, reflected, autoload_with=connection)
                actual = [
                    tuple(row)
                    for row in connection.execute(sa.select(*(table.c[column] for column in old_columns[name])))
                ]
                assert actual == before[name]
                assert connection.execute(sa.select(table.c.actor_subject_type, table.c.actor_subject_id)).one() == (
                    None,
                    None,
                )
                assert all(
                    table.c[column].nullable and table.c[column].server_default is None for column in SUBJECT_COLUMNS
                )
                assert (
                    isinstance(table.c.actor_subject_type.type, sa.String)
                    and table.c.actor_subject_type.type.length == 32
                )
                assert isinstance(table.c.actor_subject_id.type, sa.BigInteger)
            indexes = sa.inspect(connection).get_indexes(TABLES[1])
            actual_index = next(item for item in indexes if item["name"] == "ix_kpr_job_subject")
            assert actual_index["column_names"] == INDEX_COLUMNS and not actual_index["unique"]
            assert not any(
                re.match(r"\s*SELECT\b.*actor_reference", statement, re.I | re.S) for statement in migration_statements
            )
    finally:
        engine.dispose()


def test_current_model_creation_before_revision_needs_no_duplicate_ddl():
    engine = sa.create_engine("sqlite://")
    try:
        for model in (KnowledgeProcessingJob, KnowledgeProcessingRetryReceipt):
            model.__table__.create(engine)
        with engine.connect() as connection, Operations.context(MigrationContext.configure(connection)):
            seen = []
            sa.event.listen(
                connection, "before_cursor_execute", lambda _c, _cu, statement, _p, _ct, _m: seen.append(statement)
            )
            migration().upgrade()
            assert not any(re.match(r"\s*(ALTER|CREATE|INSERT|UPDATE|DELETE)\b", statement, re.I) for statement in seen)
    finally:
        engine.dispose()


def test_missing_tables_are_left_to_model_discovery():
    engine = sa.create_engine("sqlite://")
    try:
        with engine.connect() as connection, Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
            assert sa.inspect(connection).get_table_names() == []
    finally:
        engine.dispose()


def test_downgrade_requires_consistent_backup():
    with pytest.raises(RuntimeError, match="backup"):
        migration().downgrade()
