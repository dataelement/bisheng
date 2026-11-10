"""Coverage AC: AC-43, AC-48, AC-51, AC-52, AC-53.

The real CLI composes real repositories and caller-owned SQL transactions. Only
shared configuration and the database-session infrastructure port are replaced.
SQLite proves CLI/transaction semantics, not MySQL/DM8 lock or crash durability.
No fixture supplies another CLI implementation or a maintenance business stub.
"""

import importlib.util
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, select

from bisheng.core.context import tenant as context
from bisheng.core.database import tenant_filter
from bisheng.database.models.tenant import Tenant
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent as Fact
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request
from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSetting as Setting
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.repositories import content_safety
from bisheng.dsh.domain.repositories.content_safety_queries import ContentSafetyQueryRepository
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository as Settings
from test.dsh.content_safety_fixtures import SafetyIdentity, safety_database
from test.dsh.model_audit_fixtures import AUDIT_MODELS
from test.dsh.test_content_safety_repository import decoded, tenant_session, wire_hash
from test.dsh.test_content_safety_retention import counts, maintenance, seed

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/dsh_content_safety_maintenance.py"
SCOPES = (
    context.current_tenant_id,
    context._admin_scope_tenant_id,
    context.visible_tenant_ids,
    context._bypass_tenant_filter,
    context._strict_tenant_filter,
    context._is_management_api,
)


def scope_snapshot():
    return tuple(variable.get() for variable in SCOPES)


@pytest.fixture
def cli_engine(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "maintenance-cli.sqlite"))
    models = (*AUDIT_MODELS, DshModelCall, DshMonthlyUsage, Tenant)
    with safety_database(engine=engine):
        SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in models])
        tenant_filter._tenant_aware_tables.update(
            model.__tablename__ for model in models if "tenant_id" in model.__table__.columns
        )
        with Session(engine) as session, session.begin():
            session.add_all(
                [
                    Tenant(id=101, tenant_code="cli-101", tenant_name="CLI tenant 101"),
                    Tenant(id=202, tenant_code="cli-202", tenant_name="CLI tenant 202", status="disabled"),
                ]
            )
        yield engine
    engine.dispose()


@pytest.fixture
def cli(monkeypatch, cli_engine, capfd):
    from bisheng.common.services import config_service
    from bisheng.core import database
    from bisheng.core.context import manager as app_context

    configured = SimpleNamespace(database_url=str(cli_engine.url), multi_tenant=SimpleNamespace(enabled=True))
    opened = []
    statements = []

    @contextmanager
    def sessions():
        opened.append(scope_snapshot())
        with Session(cli_engine, expire_on_commit=True) as session:
            yield session

    def observe(_connection, _cursor, statement, _parameters, _execution, _many):
        statements.append((statement, scope_snapshot()))

    def forbidden_infrastructure(*_args, **_kwargs):
        raise AssertionError("DB-only CLI must not initialize unrelated middleware")

    monkeypatch.setattr(app_context, "initialize_app_context", forbidden_infrastructure)
    monkeypatch.setattr(config_service, "settings", configured)
    monkeypatch.setattr(database, "get_sync_db_session", sessions)
    event.listen(cli_engine, "before_cursor_execute", observe)
    try:
        spec = importlib.util.spec_from_file_location("f111_content_safety_maintenance_cli", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.settings is configured, "Use the live service's shared configuration singleton"
        yield SimpleNamespace(
            module=module, engine=cli_engine, settings=configured, opened=opened, statements=statements, capfd=capfd
        )
    finally:
        event.remove(cli_engine, "before_cursor_execute", observe)


def invoke(cli, *arguments):
    before = scope_snapshot()
    cli.capfd.readouterr()
    cli.opened.clear()
    cli.statements.clear()
    try:
        try:
            status = cli.module.main(list(arguments))
        except SystemExit as error:
            status = error.code
        output = cli.capfd.readouterr()
    finally:
        assert scope_snapshot() == before, "CLI must restore every inherited tenant/admin scope"
    return status, output.out, output.err


def success(cli, *arguments):
    status, stdout, stderr = invoke(cli, *arguments)
    assert status == 0, stderr
    reports = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    assert reports and all(report["tenant_id"] == 101 for report in reports)
    return reports


def snapshot(engine):
    tables = (*AUDIT_MODELS, DshModelCall, DshMonthlyUsage, Fact, Tenant)
    with engine.connect() as connection:
        return {
            model.__tablename__: sorted(repr(tuple(row)) for row in connection.execute(select(model.__table__)))
            for model in tables
        }


def assert_no_writes(cli):
    mutating = ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "TRUNCATE", "REPLACE")
    assert not [sql for sql, _scope in cli.statements if sql.lstrip().upper().startswith(mutating)]


def append_only(engine, make, *, tenant=101, **changes):
    actor = SafetyIdentity() if tenant == 101 else SafetyIdentity(202, 22, 8, "20200000-0000-4000-8000-000000000002")
    raw = make(identity=actor, **changes)
    with tenant_session(engine, tenant) as session, session.begin():
        content_safety.append_event(session, decoded(raw), wire_hash(raw))
    return raw


@pytest.mark.parametrize("command", ["rebuild", "purge-details", "purge-audit"])
def test_default_dry_run_preserves_all_rows_and_sends_no_dml_or_schema_initialization(
    cli, content_safety_event, content_safety_clock, command
):
    cutoff = content_safety_clock.now()
    seed(cli.engine, content_safety_event, received_at=cutoff - timedelta(days=365))
    seed(cli.engine, content_safety_event, tenant=202, received_at=cutoff - timedelta(days=365))
    before = snapshot(cli.engine)
    options = [] if command == "rebuild" else ["--before", cutoff.isoformat()]
    reports = success(cli, command, "--tenant-id", "101", *options)
    assert all(report["apply"] is False and report["operation"] == command for report in reports)
    assert_no_writes(cli)
    assert snapshot(cli.engine) == before


@pytest.mark.parametrize(
    "arguments",
    [
        ["rebuild", "--apply"],
        ["rebuild", "--tenant-id", "0", "--apply"],
        ["rebuild", "--tenant-id", "-1", "--apply"],
        ["rebuild", "--tenant-id", "bad", "--apply"],
        ["rebuild", "--tenant-id", "101", "--batch-size", "0", "--apply"],
        ["rebuild", "--tenant-id", "101", "--batch-size", "101", "--apply"],
        ["rebuild", "--tenant-id", "101", "--max-batches", "0", "--apply"],
        ["rebuild", "--tenant-id", "101", "--max-batches", "10001", "--apply"],
        ["purge-details", "--tenant-id", "101", "--apply"],
        ["purge-audit", "--tenant-id", "101", "--apply"],
    ],
)
def test_invalid_or_incomplete_apply_arguments_fail_before_opening_database(cli, arguments):
    before = snapshot(cli.engine)
    status, _stdout, stderr = invoke(cli, *arguments)
    assert status != 0 and stderr
    assert not cli.opened and not cli.statements
    assert snapshot(cli.engine) == before


@pytest.mark.parametrize("cutoff", ["2026-10-23", "2026-10-23T02:00:00", "not-a-date", "2026-13-23T02:00:00Z"])
def test_purge_cutoff_requires_explicit_valid_timezone_before_any_database_access(cli, cutoff):
    status, _stdout, stderr = invoke(cli, "purge-audit", "--tenant-id", "101", "--before", cutoff, "--apply")
    assert status != 0 and stderr and not cli.opened
    assert_no_writes(cli)


@pytest.mark.parametrize("database_url", [None, ""])
def test_missing_service_database_configuration_fails_without_fallback_or_initialization(cli, database_url):
    cli.settings.database_url = database_url
    status, _stdout, stderr = invoke(cli, "rebuild", "--tenant-id", "101", "--apply")
    assert status != 0 and stderr and not cli.opened
    assert_no_writes(cli)


def test_unknown_positive_tenant_is_rejected_without_creating_setting_or_rows(cli):
    before = snapshot(cli.engine)
    status, _stdout, stderr = invoke(cli, "rebuild", "--tenant-id", "303", "--apply")
    assert status != 0 and stderr
    assert_no_writes(cli)
    assert snapshot(cli.engine) == before


@pytest.mark.parametrize("tenant_status", ["disabled", "archived"])
def test_retained_history_of_disabled_or_archived_tenant_is_still_maintainable(
    cli, content_safety_event, tenant_status
):
    with Session(cli.engine) as session, session.begin():
        tenant = session.get(Tenant, 202)
        tenant.status = tenant_status
        session.add(tenant)
    append_only(cli.engine, content_safety_event, tenant=202)
    status, stdout, stderr = invoke(cli, "rebuild", "--tenant-id", "202", "--apply")
    assert status == 0, stderr
    assert json.loads(stdout.splitlines()[-1])["examined"] == 1
    assert counts(cli.engine, 202) == (1, 1) and counts(cli.engine) == (0, 0)


def test_rebuild_apply_is_finite_resumable_tenant_bound_and_idempotent(cli, content_safety_event):
    originals = [append_only(cli.engine, content_safety_event) for _ in range(3)]
    append_only(cli.engine, content_safety_event, tenant=202)
    first = success(cli, "rebuild", "--tenant-id", "101", "--apply", "--batch-size", "1")
    assert len(first) == 1 and first[0]["examined"] == 1 and first[0]["skipped_expired"] == 0
    cursor = first[0]["next_cursor"]
    assert isinstance(cursor, str) and cursor and counts(cli.engine) == (1, 3)
    rest = success(
        cli, "rebuild", "--tenant-id", "101", "--apply", "--batch-size", "1", "--max-batches", "3", "--cursor", cursor
    )
    assert len(rest) == 2 and sum(report["examined"] for report in rest) == 2
    assert rest[-1]["next_cursor"] is None and counts(cli.engine) == (3, 3)
    success(cli, "rebuild", "--tenant-id", "101", "--apply", "--max-batches", "3", "--batch-size", "1")
    assert counts(cli.engine) == (3, 3) and counts(cli.engine, 202) == (0, 1)
    with tenant_session(cli.engine) as session:
        assert {fact.payload_hash for fact in session.exec(select(Fact))} == {wire_hash(raw) for raw in originals}
    status, _stdout, stderr = invoke(cli, "rebuild", "--tenant-id", "202", "--apply", "--cursor", cursor)
    assert status != 0 and stderr and counts(cli.engine, 202) == (0, 1)


def test_rebuild_reports_expired_facts_as_skipped_instead_of_claiming_recovery(
    cli, content_safety_event, content_safety_clock
):
    before = content_safety_clock.now()
    append_only(cli.engine, content_safety_event, request_started_at=(before - timedelta(days=31)).isoformat())
    with tenant_session(cli.engine) as session, session.begin():
        Settings(session).begin_cleanup(before=before)
    reports = success(cli, "rebuild", "--tenant-id", "101", "--apply")
    assert reports[-1]["examined"] == reports[-1]["skipped_expired"] == 1
    assert counts(cli.engine) == (0, 1)


@pytest.mark.parametrize("existing_checkpoint", [False, True])
def test_explicit_detail_purge_normalizes_timezone_keeps_summary_and_never_changes_audit_watermark(
    cli, content_safety_event, content_safety_clock, existing_checkpoint
):
    cutoff = content_safety_clock.now()
    if existing_checkpoint:
        seed(cli.engine, content_safety_event, received_at=cutoff - timedelta(seconds=10))
    _raw, row = seed(cli.engine, content_safety_event, received_at=cutoff - timedelta(seconds=1))
    seed(cli.engine, content_safety_event, received_at=cutoff)
    seed(cli.engine, content_safety_event, tenant=202, received_at=cutoff - timedelta(days=30))
    prior_setting = None
    if existing_checkpoint:
        with tenant_session(cli.engine) as session, session.begin():
            Settings(session).begin_cleanup(before=cutoff)
        with tenant_session(cli.engine) as session, session.begin():
            assert maintenance(session).purge_batch(limit=1)["audits_deleted"] == 1
        with tenant_session(cli.engine) as session:
            prior_setting = session.exec(select(Setting)).one().model_dump()
            assert prior_setting["cleanup_after_request_id"] is not None
    with tenant_session(cli.engine) as session:
        prior = session.get(Request, row.request_id).model_dump()
    reports = success(cli, "purge-details", "--tenant-id", "101", "--apply", "--before", "2026-10-23T10:00:00+08:00")
    assert sum(report["details_deleted"] for report in reports) == 1
    assert sum(report["audits_deleted"] for report in reports) == 0
    assert counts(cli.engine) == (2, 1) and counts(cli.engine, 202) == (1, 1)
    with tenant_session(cli.engine) as session:
        current = session.get(Request, row.request_id)
        assert current.model_dump() == prior and current.has_sensitive_hit
        assert ContentSafetyQueryRepository(session).request_events(row.request_id)["details_status"] == "PURGED"
        setting = session.exec(select(Setting)).one()
        if existing_checkpoint:
            assert setting.model_dump() == prior_setting
        else:
            assert setting.audit_deleted_before is setting.cleanup_before is None


def test_audit_purge_commits_checkpoint_before_bounded_deletes_then_resumes_without_touching_other_tenant(
    cli, content_safety_event, content_safety_clock
):
    cutoff = content_safety_clock.now()
    for seconds in (3, 2, 1):
        seed(cli.engine, content_safety_event, received_at=cutoff - timedelta(seconds=seconds))
    seed(cli.engine, content_safety_event, tenant=202, received_at=cutoff - timedelta(days=5))
    committed_cutoffs = []

    def on_delete(_connection, _cursor, sql, _parameters, _execution, _many):
        if sql.lstrip().upper().startswith("DELETE") and Request.__tablename__ in sql:
            with cli.engine.connect() as observer:
                committed_cutoffs.append(
                    observer.execute(
                        select(Setting.__table__.c.audit_deleted_before).where(Setting.tenant_id == 101)
                    ).scalar_one()
                )

    event.listen(cli.engine, "before_cursor_execute", on_delete)
    try:
        first = success(
            cli, "purge-audit", "--tenant-id", "101", "--apply", "--before", cutoff.isoformat(), "--batch-size", "1"
        )
        assert sum(report["audits_deleted"] for report in first) == 1
        assert first[-1]["has_more"] and counts(cli.engine) == (2, 2)
        rest = success(
            cli,
            "purge-audit",
            "--tenant-id",
            "101",
            "--apply",
            "--before",
            cutoff.isoformat(),
            "--batch-size",
            "1",
            "--max-batches",
            "5",
        )
        assert sum(report["audits_deleted"] for report in rest) == 2
        assert not rest[-1]["has_more"] and counts(cli.engine) == (0, 0)
    finally:
        event.remove(cli.engine, "before_cursor_execute", on_delete)
    assert committed_cutoffs and all(value == cutoff.replace(tzinfo=None) for value in committed_cutoffs)
    assert counts(cli.engine, 202) == (1, 1)


def test_cli_apply_clears_ambient_admin_bypass_for_sql_and_restores_every_scope(cli, content_safety_event):
    append_only(cli.engine, content_safety_event)
    tokens = [
        variable.set(value)
        for variable, value in zip(SCOPES, (202, 999, frozenset({101, 202}), True, False, True), strict=True)
    ]
    try:
        success(cli, "rebuild", "--tenant-id", "101", "--apply")
        assert cli.opened and all(scope[:4] == (101, None, frozenset({101}), False) for scope in cli.opened)
        assert cli.statements and all(
            scope[:4] == (101, None, frozenset({101}), False) for _sql, scope in cli.statements
        )
    finally:
        for token in reversed(tokens):
            token.var.reset(token)


def test_database_failure_is_nonzero_without_sql_credentials_or_traceback_and_restores_scope(cli, monkeypatch):
    private = "synthetic-private-db-password-and-payload"

    @contextmanager
    def unavailable():
        raise OperationalError("SELECT private_fact FROM credentials", {"password": private}, RuntimeError(private))
        yield

    monkeypatch.setattr(cli.module, "get_sync_db_session", unavailable)
    status, stdout, stderr = invoke(cli, "rebuild", "--tenant-id", "101", "--apply")
    assert status != 0 and stderr
    combined = stdout + stderr
    assert private not in combined and "private_fact" not in combined and "Traceback" not in combined
    assert_no_writes(cli)


def test_direct_script_help_bootstraps_without_database_or_middleware(tmp_path):
    config = tmp_path / "empty-service-config.yaml"
    config.write_text("{}\n", encoding="utf-8")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("BS_")}
    environment.update(config=str(config), PYTHONDONTWRITEBYTECODE="1")
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert all(command in result.stdout for command in ("rebuild", "purge-details", "purge-audit"))
    assert "Traceback" not in result.stderr


def test_fixture_retains_two_real_independent_tenants_without_cli_business_replacement(
    cli_engine, content_safety_event, content_safety_clock
):
    cutoff = content_safety_clock.now()
    for tenant in (101, 202):
        seed(cli_engine, content_safety_event, tenant=tenant, received_at=cutoff - timedelta(days=365))
    assert counts(cli_engine) == counts(cli_engine, 202) == (1, 1)
    before = snapshot(cli_engine)
    with tenant_session(cli_engine) as session, session.begin():
        assert {row.tenant_id for row in session.exec(select(Request))} == {101}
    assert snapshot(cli_engine) == before


def test_batch_failure_rolls_back_delete_but_keeps_independently_committed_watermark(
    cli, content_safety_event, content_safety_clock
):
    cutoff = content_safety_clock.now()
    seed(cli.engine, content_safety_event, received_at=cutoff - timedelta(days=31))
    marker = "synthetic-private-batch-fault"

    def fail_delete(_connection, _cursor, statement, _parameters, _execution, _many):
        if statement.lstrip().upper().startswith("DELETE"):
            raise OperationalError("DELETE private_fact", {}, RuntimeError(marker))

    event.listen(cli.engine, "before_cursor_execute", fail_delete)
    try:
        status, stdout, stderr = invoke(
            cli, "purge-audit", "--tenant-id", "101", "--apply", "--before", cutoff.isoformat()
        )
    finally:
        event.remove(cli.engine, "before_cursor_execute", fail_delete)
    assert status != 0 and stderr and marker not in stdout + stderr and "private_fact" not in stdout + stderr
    assert counts(cli.engine) == (1, 1)
    with tenant_session(cli.engine) as session:
        setting = session.exec(select(Setting)).one()
        assert setting.audit_deleted_before == setting.cleanup_before == cutoff.replace(tzinfo=None)
    reports = success(cli, "purge-audit", "--tenant-id", "101", "--apply", "--before", cutoff.isoformat())
    assert reports[-1]["audits_deleted"] == 1 and counts(cli.engine) == (0, 0)


def test_commit_failure_never_prints_success_or_leaves_half_rebuilt_projection(cli, content_safety_event):
    append_only(cli.engine, content_safety_event)

    def fail_commit(_session):
        raise OperationalError("COMMIT private_transaction", {}, RuntimeError("synthetic-private-commit"))

    event.listen(Session, "before_commit", fail_commit)
    try:
        status, stdout, stderr = invoke(cli, "rebuild", "--tenant-id", "101", "--apply")
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert status != 0 and stderr and not stdout.strip()
    assert "private_transaction" not in stderr and "synthetic-private-commit" not in stderr
    assert counts(cli.engine) == (0, 1)


@pytest.mark.parametrize("failure", ["invalid_yaml", "missing_table"])
def test_standalone_cli_reports_configuration_and_real_database_errors_without_raw_logs(tmp_path, failure):
    config = tmp_path / "synthetic-failure.yaml"
    marker = "synthetic-private-cli-config-marker"
    if failure == "invalid_yaml":
        config.write_text("database_url: [" + marker + "\n", encoding="utf-8")
    else:
        database = tmp_path / "private-cli-empty.sqlite"
        config.write_text("database_url: sqlite:///" + str(database) + "\n", encoding="utf-8")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("BS_")}
    environment.update(config=str(config), PYTHONDONTWRITEBYTECODE="1")
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "rebuild", "--tenant-id", "101", "--apply"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0 and result.stderr
    assert not result.stdout.strip(), "A failed standalone operation must not print a success report"
    combined = result.stdout + result.stderr
    for private in (marker, "Traceback", "SELECT", "tenant.id", "private-cli-empty", str(config)):
        assert private not in combined
