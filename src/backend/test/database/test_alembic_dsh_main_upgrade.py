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


def test_main_upgrade_contains_native_auth_and_unified_credit_revisions():
    scripts = _script_directory()
    assert scripts.get_heads() == ["f062_credit_multiplier"]
    steps = scripts._upgrade_revs("head", MANIFEST["head"])
    assert [(step.revision.revision, step.revision.down_revision) for step in steps] == [
        ("work110_dsh_local_sessions", MANIFEST["head"]),
        ("f062_unified_model_access", "work110_dsh_local_sessions"),
        ("f062_credit_multiplier", "f062_unified_model_access"),
    ]
    assert {file.name for file in VERSIONS.glob("*.py")} - MANIFEST["files"].keys() == {
        "v3_0_0_work110_dsh_local_sessions.py",
        "f062_unified_model_access.py",
        "f062_credit_multiplier.py",
    }


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
