"""Work-110 extends main, never an unrelated environment's deployed revision."""

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from test.database.test_alembic_single_head import _script_directory

BACKEND = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((Path(__file__).parent / "fixtures/work110_main_migrations.json").read_text())
VERSIONS = BACKEND / "bisheng/core/database/alembic/versions"


def test_main_migrations_are_byte_for_byte_unchanged():
    assert len(MANIFEST["files"]) == 83
    for filename, expected in MANIFEST["files"].items():
        assert hashlib.sha256((VERSIONS / filename).read_bytes()).hexdigest() == expected, filename


def test_main_upgrade_keeps_work110_revision_on_original_main_baseline():
    scripts = _script_directory()
    steps = scripts._upgrade_revs("work110_dsh_local_sessions", MANIFEST["head"])
    assert [(step.revision.revision, step.revision.down_revision) for step in steps] == [
        ("work110_dsh_local_sessions", MANIFEST["head"]),
    ]
    assert "v3_0_0_work110_dsh_local_sessions.py" not in MANIFEST["files"]
    assert "work110_dsh_local_sessions" in {revision.revision for revision in scripts.walk_revisions()}


@pytest.mark.parametrize("uppercase", [False, True])
def test_seat_ddl_preserves_mysql_and_dm_reflected_identifier_case(monkeypatch, uppercase):
    revision = _script_directory().get_revision("work110_dsh_local_sessions").module

    def name(value):
        return value.upper() if uppercase else value

    inspector = Mock()
    inspector.get_table_names.return_value = [name("dsh_model_call")]
    inspector.get_columns.return_value = [
        {"name": name(column), "nullable": False} for column in ("seat_id", "grant_version")
    ]
    inspector.get_check_constraints.return_value = [{"name": name("ck_dsh_call_versions")}]
    operations = Mock()
    monkeypatch.setattr(revision, "op", operations)
    monkeypatch.setattr(revision.sa, "inspect", lambda connection: inspector)
    revision.upgrade()
    assert [(call.args[:2], call.kwargs["nullable"]) for call in operations.alter_column.call_args_list] == [
        ((name("dsh_model_call"), name("seat_id")), True),
        ((name("dsh_model_call"), name("grant_version")), True),
    ]
    operations.drop_constraint.assert_called_once_with(
        name("ck_dsh_call_versions"), name("dsh_model_call"), type_="check"
    )
    assert "grant_version IS NULL" in operations.create_check_constraint.call_args.args[2]
    operations.create_table.assert_not_called()
    operations.execute.assert_not_called()


def test_main_upgrade_preserves_native_auth_credits_and_safety_ancestry():
    """Coverage AC: AC-52, AC-53."""
    scripts = _script_directory()
    assert len(scripts.get_heads()) == 1
    steps = scripts._upgrade_revs("head", MANIFEST["head"])
    chain = [(step.revision.revision, step.revision.down_revision) for step in steps]
    assert [
        item
        for item in chain
        if item[0]
        in {
            "work110_dsh_local_sessions",
            "f062_unified_model_access",
            "f062_credit_multiplier",
            "f111_dsh_content_safety",
        }
    ] == [
        ("work110_dsh_local_sessions", MANIFEST["head"]),
        ("f062_unified_model_access", "work110_dsh_local_sessions"),
        ("f062_credit_multiplier", "f062_unified_model_access"),
        ("f111_dsh_content_safety", "f062_credit_multiplier"),
    ]
    # Future descendants may extend the line, but every added file must be on it.
    assert {file.name for file in VERSIONS.glob("*.py")} - MANIFEST["files"].keys() == {
        Path(step.revision.path).name for step in steps
    }


def test_published_credit_revisions_are_byte_for_byte_unchanged():
    """Keep published credit DDL intact when extending its migration head."""
    expected = {
        "f062_unified_model_access.py": "9ccbd5156e5c060ca415d200ee530c36551e2233ecf0da184e75f594473e9146",
        "f062_credit_multiplier.py": "cfb8105f7b5ad4fa13aca0f3db962de8380e6f18589cf628ccb31d004f2dd194",
    }
    for filename, digest in expected.items():
        assert hashlib.sha256((VERSIONS / filename).read_bytes()).hexdigest() == digest, filename


def _f111():
    return _script_directory().get_revision("f111_dsh_content_safety").module


def _safety_tables():
    from bisheng.dsh.domain.models.model_audit_conversation import DshModelAuditConversation
    from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
    from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSetting
    from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeNode, DshAuditTreeState

    return {
        model.__tablename__: model.__table__
        for model in (
            DshModelAuditRequest,
            DshModelAuditSetting,
            DshModelAuditConversation,
            DshAuditTreeState,
            DshAuditTreeNode,
        )
    }


def test_f111_model_and_upgrade_schema_match():
    """Offline MySQL compilation is parity evidence, not a real database upgrade."""
    from sqlalchemy.dialects.mysql import dialect
    from sqlalchemy.schema import CreateColumn

    revision = _f111()
    tables = _safety_tables()
    for name, columns in revision._columns().items():
        for column in columns:
            expected = tables[name].c[column.name]
            assert str(CreateColumn(column).compile(dialect=dialect())) == str(
                CreateColumn(expected).compile(dialect=dialect())
            ), (name, column.name)
    for table, name, columns in revision._INDEXES:
        expected = next(index for index in tables[table].indexes if index.name == name)
        assert tuple(column.name for column in expected.columns) == columns
    mode = next(check for check in tables["dsh_model_audit_request"].constraints if check.name == "ck_dma_request_mode")
    assert str(mode.sqltext) == revision._MODE_CHECK


@pytest.mark.parametrize("fresh", [False, True])
def test_f111_repeated_upgrade_control_flow_is_schema_only(monkeypatch, fresh):
    """Record operations without claiming SQL execution on MySQL or DM8."""
    revision = _f111()
    tables = _safety_tables()
    columns = {table: set(model.c.keys()) for table, model in tables.items()}
    if not fresh:
        for table, new_columns in revision._columns().items():
            columns[table] -= {column.name for column in new_columns}
    nullables = dict.fromkeys(
        ("session_id", "effective_mode", "model_result", "response_result", "usage_settlement"), fresh
    )
    indexes = {name for _, name, _ in revision._INDEXES} if fresh else set()
    uniques = {"uq_dma_safety_request"} if fresh else set()
    checks = {"ck_dma_request_mode", "ck_dma_request_origin"} if fresh else {"ck_dma_request_mode"}
    operations = Mock()

    def add_column(table, column):
        assert column.name not in columns[table]
        columns[table].add(column.name)

    def alter_column(table, name, **kwargs):
        assert kwargs["nullable"] is True
        nullables[name] = True

    def add_check(name, table, expression):
        assert name not in checks
        checks.add(name)

    operations.add_column.side_effect = add_column
    operations.alter_column.side_effect = alter_column
    operations.drop_constraint.side_effect = lambda name, table, **kwargs: checks.remove(name)
    operations.create_check_constraint.side_effect = add_check
    operations.create_unique_constraint.side_effect = lambda name, table, values: uniques.add(name)
    operations.create_index.side_effect = lambda name, table, values: indexes.add(name)
    monkeypatch.setattr(revision, "op", operations)
    monkeypatch.setattr(revision, "table_exists", lambda table: table in tables)
    monkeypatch.setattr(revision, "column_exists", lambda table, name: name in columns[table])
    monkeypatch.setattr(revision, "is_column_nullable", lambda bind, table, name: nullables[name])
    monkeypatch.setattr(
        revision, "get_check_constraint", lambda table, name: {"name": name} if name in checks else None
    )
    monkeypatch.setattr(revision, "unique_constraint_exists", lambda table, name: name in uniques)
    monkeypatch.setattr(revision, "index_exists", lambda table, name: name in indexes)
    revision.upgrade()
    assert columns == {table: set(model.c.keys()) for table, model in tables.items()}
    assert all(nullables.values())
    assert checks == {"ck_dma_request_mode", "ck_dma_request_origin"}
    operations.execute.assert_not_called()
    operations.create_table.assert_not_called()
    operations.reset_mock()
    revision.upgrade()
    for name in ("add_column", "alter_column", "create_unique_constraint", "create_index", "execute"):
        getattr(operations, name).assert_not_called()
    assert operations.drop_constraint.call_count == operations.create_check_constraint.call_count == 1


@pytest.mark.parametrize("uppercase", [False, True])
def test_f111_constraint_helpers_preserve_reflected_names(monkeypatch, uppercase):
    from bisheng.core.database.alembic_helpers import online

    def name(value):
        return value.upper() if uppercase else value

    inspector = Mock()
    inspector.get_table_names.return_value = [name("dsh_model_audit_request")]
    inspector.get_check_constraints.return_value = [{"name": name("ck_dma_request_mode")}]
    inspector.get_unique_constraints.return_value = [{"name": name("uq_dma_safety_request")}]
    monkeypatch.setattr(online, "inspect", lambda connection: inspector)
    monkeypatch.setattr(online.op, "get_bind", lambda: object())
    assert online.get_check_constraint("dsh_model_audit_request", "ck_dma_request_mode") == {
        "name": name("ck_dma_request_mode")
    }
    assert online.unique_constraint_exists("dsh_model_audit_request", "uq_dma_safety_request")
    inspector.get_check_constraints.assert_called_once_with(name("dsh_model_audit_request"))
    inspector.get_unique_constraints.assert_called_once_with(name("dsh_model_audit_request"))
    assert online.get_check_constraint("missing_table", "ck_dma_request_mode") is None
    assert not online.unique_constraint_exists("missing_table", "uq_dma_safety_request")


def test_f111_downgrade_refuses_destructive_changes(monkeypatch):
    revision = _f111()
    operations = Mock()
    monkeypatch.setattr(revision, "op", operations)
    with pytest.raises(RuntimeError, match="must be retained"):
        revision.downgrade()
    assert not operations.mock_calls
