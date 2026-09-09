"""Offline SQL portability guards; a missing real DM compiler remains an explicit skip."""

import ast
import importlib
from pathlib import Path

import pytest
from sqlalchemy import CLOB, JSON
from sqlalchemy.dialects.mysql import dialect as MySQLDialect
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.schema import CreateColumn, CreateIndex, CreateTable

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.database.dialect_helpers import JsonType
from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.models.user_policy import DshUserPolicy, ModelConfigsType
from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig

BACKEND = Path(__file__).resolve().parents[2]
MODELS = (DshUserPolicy, DshAdminOperation, DshMonthlyUsage, DshModelCall)


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _call_name(node.value) + "." + node.attr
    return ""


def _raw_sql_calls(source):
    """Reject raw SQL entry points, allowing only ORM schema default expressions."""
    tree = ast.parse(source)
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sqlalchemy"):
            aliases.update({item.asname or item.name: item.name for item in node.names})
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func).split(".")[-1]
        name = aliases.get(name, name)
        if name in {"text", "literal_column"}:
            parent = parents.get(node)
            # Column defaults/onupdate and DDL constraints are schema, not handwritten DML.
            if isinstance(parent, ast.keyword) and parent.arg in {"server_default", "default", "onupdate"}:
                continue
            violations.append(node.lineno)
        elif name == "exec_driver_sql":
            violations.append(node.lineno)
        elif name in {"execute", "exec", "scalar", "scalars"} and node.args:
            if isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)) or (
                isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
            ):
                violations.append(node.lineno)
    return violations


def test_dsh_business_and_migration_have_no_raw_sql_entry_points():
    files = sorted((BACKEND / "bisheng/dsh").rglob("*.py"))
    files += [
        BACKEND / "bisheng/user/domain/repositories/dsh_profile.py",
        BACKEND / "bisheng/core/database/alembic/versions/v3_0_0_f062_profile_version.py",
    ]
    violations = []
    for source_file in files:
        source = source_file.read_text()
        violations.extend(f"{source_file.relative_to(BACKEND)}:{line}" for line in _raw_sql_calls(source))
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and "sqlalchemy.dialects.mysql" in (node.module or ""):
                violations.append(f"{source_file.relative_to(BACKEND)}:{node.lineno}: MySQL-specific import")
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize(
    "source",
    [
        "from sqlalchemy import text as sql; session.execute(sql('SELECT * FROM users'))",
        "connection.exec_driver_sql('UPDATE users SET active = 1')",
        "session.exec('DELETE FROM users')",
        "session.execute(f'SELECT * FROM {table}')",
    ],
)
def test_raw_sql_guard_detects_executable_sql(source):
    assert _raw_sql_calls(source)


def test_raw_sql_guard_allows_schema_defaults_and_orm_queries():
    assert not _raw_sql_calls("""
Column(Integer, server_default=text('0'), onupdate=sa.text('CURRENT_TIMESTAMP'))
CheckConstraint('version >= 0')
session.exec(select(User).where(User.user_id == user_id).with_for_update())
""")


@pytest.fixture(params=["mysql", "dm"])
def sql_dialect(request):
    if request.param == "mysql":
        return MySQLDialect()
    try:
        module = importlib.import_module("dmSQLAlchemy.base")
    except ImportError as exc:
        pytest.skip(f"Real dmSQLAlchemy compiler unavailable: {exc}; no Oracle substitute is used")
    return module.DMDialect()


def test_model_ddl_and_profile_column_compile_with_real_dialect(sql_dialect):
    from bisheng.user.domain.models.user import User

    for model in MODELS:
        ddl = str(CreateTable(model.__table__).compile(dialect=sql_dialect))
        assert model.__tablename__ in ddl
        for index in model.__table__.indexes:
            assert "CREATE INDEX" in str(CreateIndex(index).compile(dialect=sql_dialect))
        if sql_dialect.name == "dm":
            assert "ON UPDATE CURRENT_TIMESTAMP" not in ddl
            assert "AUTO_INCREMENT" not in ddl
            assert "`" not in ddl
    column_ddl = str(CreateColumn(User.__table__.c.dsh_profile_version).compile(dialect=sql_dialect))
    assert "DEFAULT 0" in column_ddl and "NOT NULL" in column_ddl


class _CapturedResult:
    def one_or_none(self):
        return None

    def __iter__(self):
        return iter(())


class _CaptureSession:
    def __init__(self):
        self.statements = []

    def exec(self, statement):
        self.statements.append(statement)
        return _CapturedResult()


def test_repository_queries_pagination_and_row_locks_compile_with_real_dialect(sql_dialect):
    from bisheng.dsh.domain.repositories.admin_operation import DshOperationRepository
    from bisheng.dsh.domain.repositories.admin_queries import DshAdminQueryRepository
    from bisheng.dsh.domain.repositories.policy import DshPolicyRepository
    from bisheng.user.domain.repositories.dsh_profile import UserDshProfileRepository

    session = _CaptureSession()
    token = set_current_tenant_id(2)
    try:
        DshPolicyRepository(session).get(20, lock=True)
        DshOperationRepository(session).get("operation", lock=True)
        DshOperationRepository(session).list_for_user(20, after_id="previous", limit=100)
        DshAdminQueryRepository(session).last_call(20)
        UserDshProfileRepository.cursor_ids(session, after_user_id=10, limit=100)
        with pytest.raises(ValueError, match="User not found"):
            UserDshProfileRepository.get_for_update(session, 20)
    finally:
        current_tenant_id.reset(token)
    assert len(session.statements) == 6
    for index, statement in enumerate(session.statements):
        compiled = statement.compile(dialect=sql_dialect)
        assert compiled.params, "User/model/cursor parameters must remain bound"
        sql = str(compiled).upper()
        assert "SELECT" in sql
        if index in {0, 1, 5}:
            assert "FOR UPDATE" in sql
        if sql_dialect.name == "dm":
            assert "`" not in sql


class _DmTypeRoutingOnly(DefaultDialect):
    """Exercise the shared adapter's name-based type routing, never compile DM SQL."""

    name = "dm"


@pytest.mark.parametrize("dialect", [MySQLDialect(), _DmTypeRoutingOnly()], ids=["mysql", "dm-type-routing-only"])
def test_json_and_typed_model_config_round_trip_through_bound_processors(dialect):
    native_type = JsonType().load_dialect_impl(dialect)
    assert isinstance(native_type, JSON if dialect.name == "mysql" else CLOB)
    payload = {"subject": "用户", "values": [None, 0, 9223372036854775807]}
    adapter = JsonType().dialect_impl(dialect)
    bound = adapter.bind_processor(dialect)(payload)
    assert isinstance(bound, str)
    assert adapter.result_processor(dialect, None)(bound) == payload
    configs = [
        DshModelQuotaConfig(model_id=17, monthly_token_limit=200),
        DshModelQuotaConfig(model_id=3, monthly_token_limit=100),
    ]
    typed_adapter = ModelConfigsType().dialect_impl(dialect)
    stored = typed_adapter.bind_processor(dialect)(configs)
    restored = typed_adapter.result_processor(dialect, None)(stored)
    assert restored == sorted(configs, key=lambda item: item.model_id)
    assert all(isinstance(item, DshModelQuotaConfig) for item in restored)
