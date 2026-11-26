"""T973: neutral move-marker storage never derives logical-ready proof."""

import importlib.util
import re
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from bisheng.core.database.dialect_helpers import JsonType
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob

TABLE, FLOOR = "knowledge_processing_job", "move_logical_marker"


def revision():
    path = Path(__file__).resolve().parents[2] / (
        "bisheng/core/database/alembic/versions/v3_1_0_beta1_f118_move_logical_marker.py"
    )
    spec = importlib.util.spec_from_file_location("floor_ddl", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_previous_head_is_the_only_parent():
    value = revision()
    assert value.revision == "f118_move_logical_marker"
    assert value.down_revision == "f118_retired_use_floor"
    assert value.branch_labels is value.depends_on is None


@pytest.mark.parametrize("existing", [False, True])
def test_upgrade_preserves_all_old_values_and_never_backfills_floor(existing):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    columns = [
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("model_key", sa.String(64)),
        sa.Column("derived_level", sa.Integer),
        sa.Column("original_json", sa.Text),
    ]
    if existing:
        columns.append(sa.Column(FLOOR, JsonType, nullable=True))
    table = sa.Table(TABLE, metadata, *columns)
    metadata.create_all(engine)
    try:
        with engine.begin() as conn:
            values = {"id": 1, "model_key": "mixed", "derived_level": 3, "original_json": '{"use":3,"raw":"保留"}'}
            if existing:
                values[FLOOR] = {"move_schema": 1, "original": ["retained"]}
            conn.execute(table.insert(), values)
        with engine.connect() as conn:
            before = tuple(conn.execute(sa.select(table)).one())
            seen = []

            def guard(_conn, _cursor, sql, _params, _context, _many):
                seen.append(sql)
                assert not re.match(r"\s*(INSERT|UPDATE|DELETE|REPLACE)\b", sql, re.I), sql
                assert not re.search(r"SELECT.+\bknowledge_processing_job\b", sql, re.I | re.S), sql

            sa.event.listen(conn, "before_cursor_execute", guard)
            with Operations.context(MigrationContext.configure(conn)):
                revision().upgrade()
                revision().upgrade()
            sa.event.remove(conn, "before_cursor_execute", guard)
            actual = sa.Table(TABLE, sa.MetaData(), autoload_with=conn)
            row = tuple(
                conn.execute(
                    sa.select(*(sa.type_coerce(col, JsonType()) if col.name == FLOOR else col for col in actual.c))
                ).one()
            )
            assert row[: len(before)] == before
            assert row[-1] == ({"move_schema": 1, "original": ["retained"]} if existing else None)
            column = actual.c[FLOOR]
            assert isinstance(column.type, (sa.Text, sa.JSON)) and column.nullable and column.server_default is None
            alters = [sql for sql in seen if sql.lstrip().upper().startswith("ALTER")]
            assert len(alters) == (0 if existing else 1)
    finally:
        engine.dispose()


def test_missing_table_is_left_to_model_create_all():
    engine = sa.create_engine("sqlite://")
    try:
        with engine.connect() as conn, Operations.context(MigrationContext.configure(conn)):
            revision().upgrade()
            revision().upgrade()
            assert not sa.inspect(conn).has_table(TABLE)
    finally:
        engine.dispose()


def test_existing_model_created_table_is_already_the_same_nullable_shape():
    engine = sa.create_engine("sqlite://")
    try:
        KnowledgeProcessingJob.__table__.create(engine)
        with engine.connect() as conn, Operations.context(MigrationContext.configure(conn)):
            revision().upgrade()
            revision().upgrade()
            columns = {row["name"]: row for row in sa.inspect(conn).get_columns(TABLE)}
            assert columns[FLOOR]["nullable"] and columns[FLOOR]["default"] is None
            assert isinstance(columns[FLOOR]["type"], (sa.Text, sa.JSON))
    finally:
        engine.dispose()


def test_downgrade_requires_the_consistent_backup():
    with pytest.raises(RuntimeError, match="backup"):
        revision().downgrade()
