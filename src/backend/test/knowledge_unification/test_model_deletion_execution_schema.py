"""The original confirmation row is the only durable model deletion anchor."""

import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.schema import CreateColumn

from bisheng.core.database.dialect_helpers import JsonType
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from test.knowledge_unification import test_model_delete_plan_repo as native

plan_tenant = native.plan_tenant
plans = native.plans
clock = native.clock
repository = native.repository
FIELDS = ("model_server_id", "model_execution_state", "model_execution_metadata")
INDEX = "ix_kop_model_execution"


def test_nullable_private_fields_are_not_confirmation_or_wire_fields():
    for name in FIELDS:
        field = KnowledgeOperationPlan.model_fields.get(name)
        assert field is not None and field.default is None and field.exclude and field.repr is False
        column = KnowledgeOperationPlan.__table__.c[name]
        assert column.nullable and column.default is column.server_default is None
        assert not column.foreign_keys
    assert isinstance(KnowledgeOperationPlan.__table__.c.model_execution_metadata.type, JsonType)
    assert isinstance(KnowledgeOperationPlan.__table__.c.model_execution_state.type, sa.String)
    assert KnowledgeOperationPlan.__table__.c.model_execution_state.type.length == 32
    index = next(index for index in KnowledgeOperationPlan.__table__.indexes if index.name == INDEX)
    assert [column.name for column in index.columns] == ["tenant_id", "model_server_id", "model_execution_state"]


async def test_actual_confirmation_hash_and_serialization_do_not_include_execution_state(plans, clock, repository):
    confirmation = await native.create(repository, plans, clock)
    row = await native.load(repository, plans, confirmation)
    before = repository._payload(row)
    original = row.request_hash, row.plan_digest
    row.model_server_id, row.model_execution_state = 1, "RESERVED"
    row.model_execution_metadata = {"batches": [{"id": 7, "checksum": "a" * 64}], "private": "marker"}
    await plans.flush()
    plans.expunge(row)
    restored = await native.load(repository, plans, confirmation)
    assert restored.model_server_id == 1 and restored.model_execution_state == "RESERVED"
    assert restored.model_execution_metadata == row.model_execution_metadata
    assert repository._payload(restored) == before
    assert (restored.request_hash, restored.plan_digest) == original
    assert not set(FIELDS) & restored.model_dump().keys()
    assert "marker" not in repr(restored)


@pytest.mark.parametrize("dialect", [mysql.dialect(), DefaultDialect()])
def test_all_execution_columns_compile_portably(dialect):
    for name in FIELDS:
        sql = str(CreateColumn(KnowledgeOperationPlan.__table__.c[name]).compile(dialect=dialect)).upper()
        assert "FOREIGN KEY" not in sql and "DEFAULT" not in sql


def test_real_revision_adds_only_nullable_columns_and_index_and_replays_idempotently(monkeypatch):
    module = importlib.import_module(
        "bisheng.core.database.alembic.versions.v3_1_0_beta1_f118_model_deletion_execution"
    )
    assert module.down_revision == "f118_move_logical_marker"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE knowledge_operation_plan (id VARCHAR(36) PRIMARY KEY, tenant_id INTEGER)"
        )
        connection.exec_driver_sql("INSERT INTO knowledge_operation_plan VALUES ('before', 101)")
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        monkeypatch.setattr(module, "table_exists", lambda table: sa.inspect(connection).has_table(table))
        monkeypatch.setattr(
            module,
            "column_exists",
            lambda table, name: name in {c["name"] for c in sa.inspect(connection).get_columns(table)},
        )
        monkeypatch.setattr(
            module,
            "index_exists",
            lambda table, name: name in {i["name"] for i in sa.inspect(connection).get_indexes(table)},
        )
        module.upgrade()
        module.upgrade()
        assert connection.exec_driver_sql("SELECT * FROM knowledge_operation_plan").one() == (
            "before",
            101,
            None,
            None,
            None,
        )
        assert [c["name"] for c in sa.inspect(connection).get_columns("knowledge_operation_plan")] == [
            "id",
            "tenant_id",
            *FIELDS,
        ]
    engine.dispose()
