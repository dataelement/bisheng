from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import MetaData, Table, UniqueConstraint
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.schema import CreateTable
from sqlalchemy.types import CLOB, JSON, Text

from bisheng.approval.domain.models.approval_decision_outbox import ApprovalDecisionOutbox
from bisheng.approval.domain.models.approval_instance import ApprovalInstance, ApprovalOutbox
from bisheng.approval.domain.repositories import (
    approval_decision_outbox_repository,
    approval_instance_repository,
    approval_query_repository,
)
from bisheng.approval.domain.services import approval_center_service, approval_exception_service, approval_gate
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeRequest,
)
from bisheng.permission.domain.models.resource_user_invite_request import (
    ResourceUserInviteRequest,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_F046_MIGRATION = (
    _BACKEND_ROOT
    / "bisheng"
    / "core"
    / "database"
    / "alembic"
    / "versions"
    / "v2_6_0_f046_knowledge_space_file_change_approval.py"
)
_F046_MIGRATION_MODULE = "bisheng.core.database.alembic.versions.v2_6_0_f046_knowledge_space_file_change_approval"


class _DmDialect(DefaultDialect):
    name = "dm"


def test_json_type_loads_expected_storage_per_dialect():
    json_type = JsonType()

    mysql_impl = json_type.load_dialect_impl(mysql.dialect())
    dm_impl = json_type.load_dialect_impl(_DmDialect())
    sqlite_impl = json_type.load_dialect_impl(sqlite.dialect())

    assert isinstance(mysql_impl, JSON)
    assert isinstance(dm_impl, CLOB)
    assert isinstance(sqlite_impl, Text)


def test_update_time_server_default_compiles_for_mysql_dm_and_sqlite():
    mysql_sql = str(UPDATE_TIME_SERVER_DEFAULT.compile(dialect=mysql.dialect()))
    dm_sql = str(UPDATE_TIME_SERVER_DEFAULT.compile(dialect=_DmDialect()))
    sqlite_sql = str(UPDATE_TIME_SERVER_DEFAULT.compile(dialect=sqlite.dialect()))

    assert mysql_sql == "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
    assert dm_sql == "CURRENT_TIMESTAMP"
    assert sqlite_sql == "CURRENT_TIMESTAMP"


def test_approval_tables_compile_without_mysql_only_fragility():
    mysql_instance_sql = str(CreateTable(ApprovalInstance.__table__).compile(dialect=mysql.dialect()))
    sqlite_instance_sql = str(CreateTable(ApprovalInstance.__table__).compile(dialect=sqlite.dialect()))
    mysql_outbox_sql = str(CreateTable(ApprovalOutbox.__table__).compile(dialect=mysql.dialect()))

    assert "payload_snapshot JSON NOT NULL" in mysql_instance_sql
    assert "detail_snapshot JSON NOT NULL" in mysql_instance_sql
    assert "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP" in mysql_instance_sql
    assert "payload_snapshot JSON NOT NULL" in mysql_outbox_sql
    assert "payload_snapshot TEXT NOT NULL" in sqlite_instance_sql
    assert "ON UPDATE CURRENT_TIMESTAMP" not in sqlite_instance_sql


def test_approval_instance_dedupe_does_not_depend_on_unique_constraint():
    table = ApprovalInstance.__table__
    forbidden_unique = {
        "tenant_id",
        "scenario_code",
        "business_key",
        "applicant_user_id",
    }

    matching_constraints = []
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            columns = {column.name for column in constraint.columns}
            if columns == forbidden_unique:
                matching_constraints.append(constraint)

    assert matching_constraints == []


def test_approval_code_avoids_mysql_json_sql_and_information_schema():
    sources = [
        inspect.getsource(approval_instance_repository),
        inspect.getsource(approval_query_repository),
        inspect.getsource(approval_gate),
        inspect.getsource(approval_center_service),
        inspect.getsource(approval_exception_service),
    ]
    combined = "\n".join(sources)

    forbidden_fragments = [
        "information_schema",
        "json_contains",
        "json_extract",
        "json_search(",
        "DATABASE()",
        "ON UPDATE CURRENT_TIMESTAMP",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in combined


def _unique_columns(table) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_decision_and_business_request_tables_compile_for_supported_dialects():
    tables = (
        ApprovalDecisionOutbox.__table__,
        ResourceUserInviteRequest.__table__,
        KnowledgeSpaceFileChangeRequest.__table__,
    )

    for table in tables:
        for dialect in (mysql.dialect(), sqlite.dialect(), _DmDialect()):
            sql = str(CreateTable(table).compile(dialect=dialect))
            assert table.name in sql
            assert "JSONB" not in sql
            assert "UUID" not in sql
            assert "ARRAY" not in sql


def test_decision_and_business_request_tables_keep_portable_deduplication_constraints():
    assert ("tenant_id", "instance_id", "decision_version") in _unique_columns(ApprovalDecisionOutbox.__table__)
    assert {
        ("tenant_id", "business_key", "active_marker"),
        ("tenant_id", "approval_instance_id"),
        ("tenant_id", "decision_event_id"),
    }.issubset(_unique_columns(ResourceUserInviteRequest.__table__))
    assert {
        ("tenant_id", "approval_instance_id"),
        ("tenant_id", "upload_stage_id"),
        ("tenant_id", "decision_event_id"),
    }.issubset(_unique_columns(KnowledgeSpaceFileChangeRequest.__table__))

    for table in (ResourceUserInviteRequest.__table__, KnowledgeSpaceFileChangeRequest.__table__):
        assert table.c.business_key.nullable is False
        assert table.c.business_key.server_default is None
        assert table.c.request_fingerprint.nullable is False
        assert table.c.request_fingerprint.server_default is None


def test_decision_outbox_repository_uses_row_lock_plus_conditional_claim_cas():
    source = inspect.getsource(approval_decision_outbox_repository)

    assert "with_for_update" in source
    assert "rowcount" in source
    assert "claim_token" in source
    assert "tenant_id" in source
    assert "on_conflict" not in source.lower()
    assert "on duplicate key" not in source.lower()


def test_unreleased_migration_only_creates_and_drops_feature_tables():
    source = _F046_MIGRATION.read_text(encoding="utf-8")
    compile(source, str(_F046_MIGRATION), "exec")

    assert 'down_revision: Union[str, Sequence[str], None] = "f048_merge_f046_f047_heads"' in source
    assert "op.create_table(" in source
    assert "op.drop_table(table_name)" in source
    assert "op.add_column" not in source
    assert "op.drop_column" not in source
    assert "op.alter_column" not in source
    assert '"approval_outbox"' not in source
    assert "deferred_deadline" not in source
    assert "heartbeat_at" not in source


def test_unreleased_migration_mysql_dm_smoke_and_model_parity(monkeypatch):
    migration = importlib.import_module(_F046_MIGRATION_MODULE)
    captured: dict[str, Table] = {}

    def create_table(name, *items):
        captured[name] = Table(name, MetaData(), *items)

    migration_op = SimpleNamespace(
        create_table=create_table,
        create_index=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(migration, "op", migration_op)
    monkeypatch.setattr(migration, "table_exists", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(migration, "index_exists", lambda *_args, **_kwargs: False)
    connection = SimpleNamespace(dialect=mysql.dialect())

    migration._create_decision_outbox_table(connection)
    migration._create_resource_user_invite_request_table(connection)
    migration._create_policy_table(connection)
    migration._create_setting_table(connection)
    migration._create_upload_stage_table(connection)
    migration._create_request_table(connection)
    migration._create_footprint_table(connection)
    migration._create_execution_step_table(connection)

    assert set(captured) == set(migration._FEATURE_TABLES)
    for table in captured.values():
        mysql_sql = str(CreateTable(table).compile(dialect=mysql.dialect()))
        dm_sql = str(CreateTable(table).compile(dialect=_DmDialect()))
        assert table.name in mysql_sql
        assert table.name in dm_sql

    model_tables = {
        ApprovalDecisionOutbox.__table__.name: ApprovalDecisionOutbox.__table__,
        ResourceUserInviteRequest.__table__.name: ResourceUserInviteRequest.__table__,
        KnowledgeSpaceFileChangeRequest.__table__.name: KnowledgeSpaceFileChangeRequest.__table__,
    }
    for table_name, model_table in model_tables.items():
        migration_table = captured[table_name]
        assert set(migration_table.c.keys()) == set(model_table.c.keys())
        assert _unique_columns(migration_table) == _unique_columns(model_table)
