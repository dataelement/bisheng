"""T971: private nullable logical-move storage carries facts, never ready authority."""

from copy import deepcopy

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.schema import CreateColumn
from sqlmodel import Session, create_engine

from bisheng.core.database.dialect_helpers import JsonType
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.schemas.processing_job import JobAccepted, ProcessingJobRead
from test.knowledge_unification.test_move_actor_subject_schema import job

FIELD = "move_logical_marker"
KINDS = ("embedding_rebuild", "file_reprocess", "file_resplit", "metadata_schema_change")


@pytest.fixture
def database(tenant_context):
    tenant_context(101)
    engine = create_engine("sqlite://")
    KnowledgeProcessingJob.__table__.create(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def test_explicit_private_nullable_json_column_has_no_ready_default_or_index():
    field = KnowledgeProcessingJob.model_fields.get(FIELD)
    assert field is not None and field.default is None and field.exclude is True and field.repr is False
    assert field.annotation == dict | None
    column = KnowledgeProcessingJob.__table__.c[FIELD]
    assert isinstance(column.type, JsonType) and column.nullable
    assert column.default is column.server_default is None
    assert not column.foreign_keys
    assert all(
        FIELD not in [value.name for value in index.columns] for index in KnowledgeProcessingJob.__table__.indexes
    )
    assert all(
        FIELD not in [value.name for value in constraint.columns]
        for constraint in KnowledgeProcessingJob.__table__.constraints
    )


@pytest.mark.parametrize("kind", [*KINDS, "move_index"])
def test_initial_jobs_never_infer_logical_ready_from_kind_or_actor(kind):
    value = job(kind, actor_subject_type="service_account", actor_subject_id=50)
    assert getattr(value, FIELD) is None
    assert value.state == "accepted" and value.pending_dispatch
    assert value.total_count == 0 and value.started_at is value.finished_at is None
    assert value.actor_reference == {"original": "untouched"}
    assert value.parameters == {} and value.scope_manifest == []


@pytest.mark.parametrize(
    "marker", [None, {}, {"private-fact": "private-native-ready", "nested": [0, False, "中文", None]}]
)
def test_storage_is_private_even_when_explicitly_requested_for_serialization(marker):
    value = job(**{FIELD: deepcopy(marker)})
    assert getattr(value, FIELD) == marker
    assert FIELD not in value.model_dump() and FIELD not in value.model_dump(mode="python")
    assert value.model_dump(include={FIELD}) == {}
    assert FIELD not in repr(value) and "private-native-ready" not in repr(value)
    assert FIELD not in value.model_dump_json()


@pytest.mark.parametrize(
    "marker", [None, {}, {"uninterpreted": {"ready-is-not-inferred": False, "unicode": "☃"}, "values": [0, None]}]
)
def test_native_none_and_dictionary_roundtrip_without_shape_or_state_interpretation(database, marker):
    value = job(**{FIELD: deepcopy(marker)})
    with Session(database, expire_on_commit=False) as session:
        session.add(value)
        session.commit()
    with Session(database) as session:
        restored = session.get(KnowledgeProcessingJob, value.id)
        assert getattr(restored, FIELD) == marker
        assert restored.state == "accepted" and restored.pending_dispatch
        assert restored.parameters == value.parameters and restored.scope_manifest == value.scope_manifest


@pytest.mark.parametrize("kind", KINDS)
def test_original_four_kinds_roundtrip_none_and_preserve_public_dtos(database, kind):
    value = job(kind)
    with Session(database, expire_on_commit=False) as session:
        session.add(value)
        session.commit()
        session.execute(
            sa.update(KnowledgeProcessingJob.__table__)
            .where(KnowledgeProcessingJob.id == value.id)
            .values(**{FIELD: sa.null()})
        )
        session.commit()
    with Session(database) as session:
        restored = session.get(KnowledgeProcessingJob, value.id)
        assert getattr(restored, FIELD) is None
        assert restored.kind == kind and restored.request_hash == "a" * 64
        assert restored.actor_user_id == 11 and restored.actor_reference == {"original": "untouched"}
    assert set(JobAccepted.model_fields) == {"job_id", "accepted", "state", "reused"}
    assert FIELD not in ProcessingJobRead.model_fields


def test_mysql_native_json_null_codec_and_nullable_ddl_are_not_sql_null_assumptions():
    column = KnowledgeProcessingJob.__table__.c[FIELD]
    dialect = mysql.dialect()
    storage = column.type.dialect_impl(dialect)
    ddl = str(CreateColumn(column).compile(dialect=dialect))
    assert "move_logical_marker JSON" in ddl and "NOT NULL" not in ddl and "DEFAULT" not in ddl
    # Codec/static proof only; this is not a live MySQL database assertion.
    assert storage.bind_processor(dialect)(None) == "null"
    result = storage.result_processor(dialect, None)
    assert result(None) is None and result("null") is None
    assert result('{"fact": 0}') == {"fact": 0}


def test_dm_static_type_routing_uses_clob_and_original_python_none_conversion():
    class DmTypeRoutingOnly(DefaultDialect):
        name = "dm"

    dialect = DmTypeRoutingOnly()
    column = KnowledgeProcessingJob.__table__.c[FIELD]
    assert isinstance(column.type.load_dialect_impl(dialect), sa.CLOB)
    assert "move_logical_marker CLOB" in str(CreateColumn(column).compile(dialect=dialect))
    assert column.type.process_bind_param(None, dialect) is None
    assert column.type.process_result_value(None, dialect) is None
    value = {"fact": ["中文", False, 0]}
    assert column.type.process_result_value(column.type.process_bind_param(value, dialect), dialect) == value
