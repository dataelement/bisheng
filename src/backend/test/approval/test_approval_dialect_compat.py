from __future__ import annotations

import inspect

from sqlalchemy import UniqueConstraint
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.schema import CreateTable
from sqlalchemy.types import CLOB, JSON, Text

from bisheng.approval.domain.models.approval_instance import ApprovalInstance, ApprovalOutbox
from bisheng.approval.domain.repositories import approval_instance_repository, approval_query_repository
from bisheng.approval.domain.services import approval_center_service, approval_exception_service, approval_gate
from bisheng.core.database.dialect_helpers import JsonType, UPDATE_TIME_SERVER_DEFAULT


class _DmDialect(DefaultDialect):
    name = 'dm'


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

    assert mysql_sql == 'CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'
    assert dm_sql == 'CURRENT_TIMESTAMP'
    assert sqlite_sql == 'CURRENT_TIMESTAMP'


def test_approval_tables_compile_without_mysql_only_fragility():
    mysql_instance_sql = str(CreateTable(ApprovalInstance.__table__).compile(dialect=mysql.dialect()))
    sqlite_instance_sql = str(CreateTable(ApprovalInstance.__table__).compile(dialect=sqlite.dialect()))
    mysql_outbox_sql = str(CreateTable(ApprovalOutbox.__table__).compile(dialect=mysql.dialect()))

    assert 'payload_snapshot JSON NOT NULL' in mysql_instance_sql
    assert 'detail_snapshot JSON NOT NULL' in mysql_instance_sql
    assert 'CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP' in mysql_instance_sql
    assert 'payload_snapshot JSON NOT NULL' in mysql_outbox_sql
    assert 'payload_snapshot TEXT NOT NULL' in sqlite_instance_sql
    assert 'ON UPDATE CURRENT_TIMESTAMP' not in sqlite_instance_sql


def test_approval_instance_dedupe_does_not_depend_on_unique_constraint():
    table = ApprovalInstance.__table__
    forbidden_unique = {
        'tenant_id',
        'scenario_code',
        'business_key',
        'applicant_user_id',
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
    combined = '\n'.join(sources)

    forbidden_fragments = [
        'information_schema',
        'json_contains',
        'json_extract',
        'json_search(',
        'DATABASE()',
        'ON UPDATE CURRENT_TIMESTAMP',
    ]
    for fragment in forbidden_fragments:
        assert fragment not in combined
