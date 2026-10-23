"""Coverage AC: AC-38, AC-39, AC-41, AC-48, AC-51, AC-52, AC-53.

Opt in with DSH_CONTENT_SAFETY_DB_INTEGRATION=1. MySQL requires the explicit
DSH_TEST_DATABASE_URL admin locator and DSH_SAFETY_MYSQL_CONTAINER, a local
Docker container labeled codex.task=F111 with a loopback published MySQL port.
DSH_SAFETY_WORK110_BACKEND/MANIFEST identify the immutable archived work110
backend and its SHA256 manifest. No private /tmp helper is required by this file.
Linux DM8 requires DSH_SAFETY_DM8_FRESH_URL/UPGRADE_URL, two separately prepared
empty DSH_TEST_F111_ schemas, dmPython/dmSQLAlchemy and
DSH_SAFETY_DM8_DB_ONLY_NETWORK=1 attesting OS-level database-only isolation.
DM8 schemas remain for operator inspection; use new empty schemas for another run.
No opt-in means no database connections. Missing DM8 is explicitly unexecuted.
Application rollback retains facts: real downgrade refuses empty and populated
schemas alike. Empty-schema contraction is the separate T131 operator procedure.
"""

import asyncio
import hashlib
import importlib.metadata
import importlib.util
import ipaddress
import json
import logging
import os
import platform
import re
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, create_engine, event, inspect, text
from sqlalchemy import select as sql_select
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
SHA = "2e6b5ae0fb1dcd2e32d480545e1d1ea57e77cd24"
TREE_DIGEST = "cae2d2cc311307faf1732b3624d25ab06c200b42d3c317e10ec9814880a7850f"
HEAD = "f111_dsh_content_safety"
OLD = "work110_dsh_local_sessions"


def baseline():
    try:
        root = Path(os.environ["DSH_SAFETY_WORK110_BACKEND"]).resolve()
        manifest = json.loads(Path(os.environ["DSH_SAFETY_WORK110_MANIFEST"]).read_text())
        files = manifest["python_files"]
        assert manifest["source_sha"] == SHA and manifest["revision"] == OLD
        assert (
            hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == TREE_DIGEST
        )
        assert {str(path.relative_to(root)) for path in root.rglob("*.py")} == set(files)
        for relative, digest in files.items():
            path = root / relative
            assert path.resolve().is_relative_to(root)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        assert not (root / "bisheng/dsh/domain/models/content_safety_event.py").exists()
        return root
    except (KeyError, OSError, ValueError, AssertionError):
        raise pytest.UsageError("An intact, explicitly supplied work110 baseline and manifest are required") from None


@contextmanager
def database_network(urls):
    allowed = {(url.host, url.port or (5236 if url.get_backend_name() == "dm" else 3306)) for url in urls}
    denied = []
    connect, connect_ex, resolve = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def check(address):
        if not isinstance(address, tuple) or address[:2] not in allowed:
            denied.append("non-database attempt")
            raise PermissionError("Only explicitly isolated database networking is permitted")

    def guarded_connect(sock, address):
        check(address)
        return connect(sock, address)

    def guarded_connect_ex(sock, address):
        check(address)
        return connect_ex(sock, address)

    def guarded_resolve(host, port, *args, **kwargs):
        check((host, port))
        return resolve(host, port, *args, **kwargs)

    def no_datagrams(*_args, **_kwargs):
        denied.append("datagram attempt")
        raise PermissionError("Datagram networking is forbidden")

    with (
        patch.object(socket.socket, "connect", guarded_connect),
        patch.object(socket.socket, "connect_ex", guarded_connect_ex),
        patch.object(socket, "getaddrinfo", guarded_resolve),
        patch.object(socket.socket, "sendto", no_datagrams),
    ):
        try:
            yield denied
        finally:
            assert not denied, "A dependency attempted non-database networking, even if it swallowed the error"


@contextmanager
def safe_connection_logging():
    logger = logging.getLogger("bisheng.core.database.connection")
    previous = logger.disabled
    logger.disabled = True
    try:
        yield
    finally:
        logger.disabled = previous


def mysql_owner(url):
    routing_options = {
        "db",
        "database",
        "schema",
        "host",
        "port",
        "unix_socket",
        "read_default_file",
        "read_default_group",
        "init_command",
    }
    if any(key.casefold() in routing_options for key in url.query):
        raise pytest.UsageError("Database target overrides in MySQL query options are forbidden")
    assert url.drivername == "mysql+pymysql" and url.host == "127.0.0.1" and url.port
    container = os.environ.get("DSH_SAFETY_MYSQL_CONTAINER")
    if not container:
        raise pytest.UsageError("Explicit owned MySQL container is required")
    endpoint = subprocess.check_output(
        ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], text=True
    ).strip()
    assert endpoint.startswith("unix://")
    raw = subprocess.check_output(
        ["docker", "inspect", "--format", "{{json .Config.Labels}}|{{json .NetworkSettings.Ports}}", container],
        text=True,
    )
    labels, ports = map(json.loads, raw.strip().split("|"))
    assert labels.get("codex.task") == "F111"
    assert any(
        port["HostIp"] == "127.0.0.1" and int(port["HostPort"]) == url.port for port in ports.get("3306/tcp", [])
    )


def isolated_dm_target(url):
    path, query = url.database, url.query.get("schema")
    if "schema" in url.query and (not isinstance(query, str) or not query):
        raise pytest.UsageError("DM8 schema must be one nonempty string selector")
    if path and query and path.upper() != query.upper():
        raise pytest.UsageError("Conflicting DM8 schema selectors are forbidden")
    schema = str(query or path or "").upper()
    if not re.fullmatch(r"DSH_TEST_F111_[A-Z0-9_]+", schema):
        raise pytest.UsageError("Explicit isolated DM8 schema is required")
    return str(ipaddress.ip_address(url.host)), url.port or 5236, schema


def reflected(engine):
    view = inspect(engine)
    result = {}
    for name in view.get_table_names():
        result[name.lower()] = {
            "columns": sorted(
                (
                    c["name"].lower(),
                    str(c["type"].compile(dialect=engine.dialect)),
                    c["nullable"],
                    str(c.get("default")),
                    str(c.get("autoincrement")),
                )
                for c in view.get_columns(name)
            ),
            "pk": tuple(view.get_pk_constraint(name).get("constrained_columns") or []),
            "unique": sorted((c["name"], tuple(c["column_names"])) for c in view.get_unique_constraints(name)),
            "indexes": sorted((i["name"], tuple(i["column_names"]), i["unique"]) for i in view.get_indexes(name)),
            "checks": sorted((c["name"], re.sub(r"\s+", "", c["sqltext"])) for c in view.get_check_constraints(name)),
        }
    return result


def legacy_data(engine):
    result = {}
    with engine.connect() as connection:
        for name in ("dsh_model_audit_request", "dsh_model_audit_setting", "dsh_model_call", "dsh_monthly_usage"):
            table = Table(name, MetaData(), autoload_with=connection)
            result[name] = [
                dict(row) for row in connection.execute(sql_select(table).where(table.c.tenant_id == 101)).mappings()
            ]
    return result


def migration_child():
    source, operation, seed = sys.argv[2:]
    source = Path(source).resolve()
    assert os.environ.get("DSH_CONTENT_SAFETY_DB_INTEGRATION") == "1"
    assert operation in {OLD, "head", "downgrade"} and seed in {"yes", "no"}
    assert seed == "no" or operation == OLD
    if operation != OLD:
        assert source == ROOT
    if operation == OLD:
        assert source == baseline()
    os.chdir(source)
    sys.path.insert(0, str(source))
    import logging

    from loguru import logger

    logging.disable(logging.CRITICAL)
    logger.disable("bisheng")
    url = make_url(os.environ["DSH_TEST_DATABASE_URL"])
    if url.get_backend_name() == "mysql":
        mysql_owner(url)
        assert re.fullmatch(r"dsh_test_f111_[0-9a-f]{32}", url.database or "")
    else:
        assert platform.system() == "Linux" and os.environ.get("DSH_SAFETY_DM8_DB_ONLY_NETWORK") == "1"
        assert url.drivername == "dm+dmPython"
        targets = [
            isolated_dm_target(make_url(os.environ["DSH_SAFETY_DM8_" + part + "_URL"])) for part in ("FRESH", "UPGRADE")
        ]
        assert targets[0] != targets[1] and isolated_dm_target(url) in targets
    with database_network([url]):
        from alembic import command
        from alembic.config import Config

        from bisheng.common.services.config_service import settings
        from bisheng.core.database import manager
        from bisheng.core.database.connection import DatabaseConnectionManager

        assert Path(sys.modules["bisheng"].__file__).resolve().is_relative_to(source)
        assert not settings.openfga.enabled
        port = DatabaseConnectionManager(url.render_as_string(hide_password=False), hide_parameters=True)
        try:
            cfg = Config(str(source / "alembic.ini"))
            with patch.object(manager, "sync_get_database_connection", return_value=port):
                command.upgrade(cfg, OLD if operation == OLD else "head")
                command.upgrade(cfg, OLD if operation == OLD else "head")
                if seed == "yes":
                    seed_legacy(port.engine)
                before = reflected(port.engine)
                if operation == "downgrade":
                    with pytest.raises(RuntimeError, match="must be retained"):
                        command.downgrade(cfg, OLD)
                    assert reflected(port.engine) == before
            with port.engine.connect() as connection:
                revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
                assert revision == (OLD if operation == OLD else HEAD)
                version = connection.dialect.server_version_info
            print(
                "F111_RESULT="
                + json.dumps(
                    {
                        "head": revision,
                        "version": version,
                        "driver_versions": {
                            package: importlib.metadata.version(package)
                            for package in (
                                "SQLAlchemy",
                                "PyMySQL" if url.get_backend_name() == "mysql" else "dmSQLAlchemy",
                            )
                        },
                        "schema": before,
                        "legacy": legacy_data(port.engine),
                    },
                    default=str,
                )
            )
        finally:
            port.close_sync()


def seed_legacy(engine):
    from sqlmodel import Session

    from bisheng.database.models.tenant import Tenant
    from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
    from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSetting
    from bisheng.dsh.domain.models.model_call import DshModelCall
    from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
    from bisheng.dsh.domain.services.profile import profile_scope

    request_id, session_id = str(uuid4()), str(uuid4())
    with profile_scope(101), Session(engine) as session, session.begin():
        session.add(Tenant(id=101, tenant_code="f111-old-101", tenant_name="Synthetic old tenant"))
        session.add(DshModelAuditSetting(tenant_id=101, mode="METADATA", version=7))
        session.add(
            DshModelAuditRequest(
                request_id=request_id,
                tenant_id=101,
                user_id=11,
                model_id=7,
                session_id=session_id,
                started_at=datetime(2026, 10, 1),
                model_result="SUCCEEDED",
                response_result="COMPLETED",
                usage_settlement="UNKNOWN",
                input_units=3,
            )
        )
        session.add(
            DshModelCall(
                request_id=request_id,
                tenant_id=101,
                user_id=11,
                model_id=7,
                session_id=session_id,
                usage_month="2026-10",
                policy_version=1,
                event_version=1,
                quota_epoch=1,
                status="USAGE_UNKNOWN",
            )
        )
        session.add(
            DshMonthlyUsage(
                tenant_id=101,
                user_id=11,
                model_id=7,
                usage_month="2026-10",
                billing_timezone="UTC",
                used_tokens=17,
                version=2,
            )
        )


if __name__ == "__main__":
    try:
        migration_child()
    except Exception as error:
        print("Real migration child failed (" + type(error).__name__ + ").", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)

from sqlalchemy.exc import DBAPIError  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from bisheng.common.errcode.dsh import (  # noqa: E402
    DshContentSafetyConflictError,
    DshContentSafetyExpiredError,
    DshContentSafetyUnavailableError,
)
from bisheng.database.models.tenant import Tenant  # noqa: E402
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent as Fact  # noqa: E402
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request  # noqa: E402
from bisheng.dsh.domain.models.model_audit_setting import DshModelAuditSetting as Setting  # noqa: E402
from bisheng.dsh.domain.models.model_audit_tree import DshAuditTreeState as State  # noqa: E402
from bisheng.dsh.domain.models.model_call import DshModelCall  # noqa: E402
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage  # noqa: E402
from bisheng.dsh.domain.repositories import content_safety, content_safety_projection  # noqa: E402
from bisheng.dsh.domain.repositories.content_safety_maintenance import (  # noqa: E402
    ContentSafetyMaintenanceRepository as Maintenance,
)
from bisheng.dsh.domain.repositories.content_safety_queries import ContentSafetyQueryRepository  # noqa: E402
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository as Queries  # noqa: E402
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository as Settings  # noqa: E402
from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository as Writer  # noqa: E402
from bisheng.dsh.domain.schemas.content_safety import ContentSafetyEvent  # noqa: E402
from bisheng.dsh.domain.schemas.model_audit_events import AuditEvent  # noqa: E402
from bisheng.dsh.domain.services.content_safety_ingest import ContentSafetyIngestService, VerifiedSource  # noqa: E402
from bisheng.dsh.domain.services.model_audit_writer import DshModelAuditWriter  # noqa: E402
from bisheng.dsh.domain.services.profile import profile_scope  # noqa: E402
from test.dsh.content_safety_fixtures import safety_database  # noqa: E402
from test.dsh.model_audit_fixtures import AUDIT_MODELS  # noqa: E402


def environment(kind):
    if os.environ.get("DSH_CONTENT_SAFETY_DB_INTEGRATION") != "1":
        pytest.skip("Explicit real-database opt-in is required; no connection attempted")
    old = baseline()
    if kind == "dm":
        values = [os.environ.get("DSH_SAFETY_DM8_" + part + "_URL") for part in ("FRESH", "UPGRADE")]
        if not all(values):
            pytest.skip("Linux DM8 schemas/driver are not configured; this dialect is unexecuted")
        assert platform.system() == "Linux" and os.environ.get("DSH_SAFETY_DM8_DB_ONLY_NETWORK") == "1"
        assert all(importlib.util.find_spec(name) for name in ("dmPython", "dmSQLAlchemy"))
        urls = [make_url(value) for value in values]
        assert all(url.drivername == "dm+dmPython" for url in urls)
        assert isolated_dm_target(urls[0]) != isolated_dm_target(urls[1]), (
            "Fresh and upgrade must select distinct actual schemas"
        )
        return old, urls
    value, container = os.environ.get("DSH_TEST_DATABASE_URL"), os.environ.get("DSH_SAFETY_MYSQL_CONTAINER")
    if not value or not container:
        raise pytest.UsageError("Explicit owned MySQL URL/container are required")
    url = make_url(value)
    assert url.drivername == "mysql+pymysql" and url.host == "127.0.0.1" and url.port
    assert not url.database or url.database.startswith("dsh_test_")
    mysql_owner(url)
    return old, [url]


@pytest.fixture(scope="module", params=["mysql", "dm"])
def pair(request, tmp_path_factory):
    old, urls = environment(request.param)
    directory = tmp_path_factory.mktemp("f111-real-db")
    directory.chmod(0o700)
    config = directory / "config.yaml"
    config.write_text("openfga:\n  enabled: false\n")
    config.chmod(0o600)
    created, connections = [], []
    admin = None
    with safe_connection_logging(), database_network(urls):
        try:
            if request.param == "mysql":
                admin = create_engine(urls[0], hide_parameters=True)
                with admin.begin() as connection:
                    assert connection.scalar(text("SELECT VERSION()")).startswith("8.0.")
                    for _ in range(2):
                        name = "dsh_test_f111_" + uuid4().hex
                        connection.execute(
                            text("CREATE DATABASE `" + name + "` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
                        )
                        created.append(name)
                urls = [urls[0].set(database=name) for name in created]
            else:
                from bisheng.core.database.connection import DatabaseConnectionManager

                for url in urls:
                    port = DatabaseConnectionManager(url.render_as_string(hide_password=False), hide_parameters=True)
                    connections.append(port)
                    with port.engine.connect() as connection:
                        actual = connection.exec_driver_sql(
                            "SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM DUAL"
                        ).scalar_one()
                        assert str(actual).upper() == isolated_dm_target(url)[2]
                        assert not inspect(connection).get_table_names(), (
                            "DM8 fixture refuses pre-existing schema objects"
                        )
            from bisheng.core.database.connection import DatabaseConnectionManager

            port = DatabaseConnectionManager(urls[0].render_as_string(hide_password=False), hide_parameters=True)
            connections.append(port)

            def migrate(url, source=ROOT, operation="head", seed=False):
                env = dict(
                    os.environ,
                    DSH_TEST_DATABASE_URL=url.render_as_string(hide_password=False),
                    config=str(config),
                    PYTHONDONTWRITEBYTECODE="1",
                )
                env.pop("PYTHONPATH", None)
                result = subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--migration-child",
                        str(source),
                        operation,
                        "yes" if seed else "no",
                    ],
                    cwd=directory,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                log = directory / ("phase-" + uuid4().hex + ".log")
                log.write_text(result.stdout + result.stderr)
                log.chmod(0o600)
                assert result.returncode == 0, "Real migration failed; protected phase log: " + str(log)
                records = [
                    json.loads(line.split("=", 1)[1])
                    for line in result.stdout.splitlines()
                    if line.startswith("F111_RESULT=")
                ]
                assert len(records) == 1
                return records[0]

            fresh = migrate(urls[0])
            before = migrate(urls[1], old, OLD, True)
            upgraded = migrate(urls[1])
            with safety_database(engine=port.engine, create_schema=False):
                yield SimpleNamespace(
                    engine=port.engine,
                    fresh=fresh,
                    before=before,
                    upgraded=upgraded,
                    migrate=lambda **kw: migrate(urls[0], **kw),
                    kind=request.param,
                )
        finally:
            for connection in connections:
                connection.close_sync()
            if admin is not None:
                for name in created:
                    assert re.fullmatch(r"dsh_test_f111_[0-9a-f]{32}", name)
                    with admin.begin() as connection:
                        connection.execute(text("DROP DATABASE `" + name + "`"))
                admin.dispose()


@pytest.fixture
def db(pair):
    def clear():
        with pair.engine.begin() as connection:
            for model in (*AUDIT_MODELS, DshModelCall, DshMonthlyUsage):
                connection.execute(model.__table__.delete().where(model.__table__.c.tenant_id.in_([101, 202])))
            connection.execute(Tenant.__table__.delete().where(Tenant.__table__.c.id.in_([101, 202])))

    clear()
    try:
        yield pair.engine
    finally:
        clear()


@contextmanager
def transaction(engine, tenant=101):
    with profile_scope(tenant), Session(engine, expire_on_commit=False) as session, session.begin():
        yield session


def digest(raw):
    return hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def service(engine, factory=None):
    return ContentSafetyIngestService(factory or (lambda: Session(engine, expire_on_commit=True)))


def ingest(engine, raw):
    return asyncio.run(service(engine).ingest(raw, VerifiedSource(raw["source_id"], int(raw["tenant_id"]))))


def stored(engine, tenant=101):
    with transaction(engine, tenant) as session:
        return session.exec(select(Fact)).all(), session.exec(select(Request)).all()


def native(clock, request_id=None, *, tenant=101, started=None):
    return AuditEvent(
        request_id=request_id or str(uuid4()),
        tenant_id=tenant,
        kind="entered",
        observed_at=clock.now(),
        metadata={
            "user_id": 11 if tenant == 101 else 22,
            "model_id": 7 if tenant == 101 else 8,
            "session_id": None,
            "conversation_id": None,
            "effective_mode": "METADATA",
            "started_at": started or clock.now(),
        },
    )


def test_fresh_archive_upgrade_schema_defaults_and_legacy_facts_match(pair):
    assert pair.fresh["head"] == pair.upgraded["head"] == HEAD and pair.before["head"] == OLD
    assert pair.fresh["schema"] == pair.upgraded["schema"]
    for table, rows in pair.before["legacy"].items():
        assert [{key: row[key] for key in rows[0]} for row in pair.upgraded["legacy"][table]] == rows
    request = pair.upgraded["legacy"]["dsh_model_audit_request"][0]
    assert request["record_origin"] == "MODEL" and request["content_safety_state"] == "UNREPORTED"
    assert not request["has_sensitive_hit"]
    assert pair.upgraded["legacy"]["dsh_model_call"][0]["total_tokens"] is None
    assert pair.upgraded["legacy"]["dsh_monthly_usage"][0]["used_tokens"] == 17


@pytest.mark.parametrize("populated", [False, True])
def test_real_downgrade_refuses_empty_and_populated_schema_without_changes(pair, db, content_safety_event, populated):
    def snapshot():
        with transaction(db) as session:
            return {
                model.__tablename__: sorted((row.model_dump() for row in session.exec(select(model))), key=repr)
                for model in (Fact, Request, DshModelCall, DshMonthlyUsage)
            }

    if populated:
        seed_legacy(db)
        ingest(db, content_safety_event())
    before = snapshot()
    outcome = pair.migrate(operation="downgrade")
    assert outcome["head"] == HEAD and outcome["schema"] == pair.fresh["schema"]
    assert snapshot() == before


@pytest.mark.parametrize("origin,mode", [("MODEL", None), ("EXTERNAL_SAFETY", "METADATA"), ("INVALID", None)])
def test_real_checks_reject_invalid_origins_and_modes(pair, db, content_safety_clock, origin, mode):
    with pytest.raises(DBAPIError) as rejected, transaction(db) as session:
        session.add(
            Request(
                request_id=str(uuid4()),
                tenant_id=101,
                user_id=11,
                model_id=7,
                started_at=content_safety_clock.now(),
                record_origin=origin,
                effective_mode=mode,
            )
        )
        session.flush()
    expected = {"ck_dma_request_mode", "ck_dma_request_origin"} if origin == "INVALID" else {"ck_dma_request_mode"}
    if pair.kind == "mysql":
        assert rejected.value.orig.args[0] == 3819
    assert any(name in str(rejected.value.orig).lower() for name in expected)
    assert stored(db) == ([], [])


def test_external_nullable_axes_json_roundtrip_and_multiple_native_null_bindings(
    db, content_safety_event, content_safety_clock
):
    raw = content_safety_event(
        conversation={"conversation_id": "验收-\u03b1-😀", "request_kind": "chat", "session_origin": "main"},
        session_id=None,
    )
    ingest(db, raw)
    facts, rows = stored(db)
    assert facts[0].stage_results == raw["stage_results"] and facts[0].stage_versions == raw["stage_versions"]
    assert facts[0].conversation["conversation_id"] == raw["conversation"]["conversation_id"]
    assert rows[0].effective_mode is rows[0].model_result is rows[0].response_result is rows[0].usage_settlement is None
    with transaction(db) as session:
        for _ in range(2):
            Writer(session).upsert_request(native(content_safety_clock))
    assert len(stored(db)[1]) == 3


def test_real_transaction_rolls_back_fact_summary_and_projection_together(db, content_safety_event):
    raw = content_safety_event()
    with pytest.raises(RuntimeError, match="synthetic rollback"), transaction(db) as session:
        content_safety.append_event(session, ContentSafetyEvent.model_validate(raw), digest(raw))
        row = content_safety_projection.merge_audit(session, ContentSafetyEvent.model_validate(raw))
        assert Queries(session).project_request(row.request_id)
        raise RuntimeError("synthetic rollback")
    assert stored(db) == ([], [])
    with transaction(db) as session:
        assert session.exec(select(State)).all() == []
    ingest(db, raw)
    assert len(stored(db)[0]) == len(stored(db)[1]) == 1


def test_two_real_sessions_recover_unique_race_in_fresh_transaction(db, content_safety_event):
    with transaction(db) as session:
        Settings(session).lock_retention()
    raw = content_safety_event()
    barrier, seen, lock = threading.Barrier(2), set(), threading.Lock()

    def after_read(_connection, _cursor, sql, _parameters, _execution, _many):
        if sql.lstrip().upper().startswith("SELECT") and "dsh_content_safety_event.event_id =" in sql:
            with lock:
                first = threading.get_ident() not in seen
                seen.add(threading.get_ident())
            if first:
                barrier.wait(timeout=5)

    async def run():
        receiver = service(db)
        source = VerifiedSource(raw["source_id"], 101)
        return await asyncio.gather(receiver.ingest(raw, source), receiver.ingest(raw, source))

    event.listen(db, "after_cursor_execute", after_read)
    try:
        receipts = asyncio.run(run())
    finally:
        event.remove(db, "after_cursor_execute", after_read)
    assert len(seen) == 2 and sorted(receipt.duplicate for receipt in receipts) == [False, True]
    assert len(stored(db)[0]) == len(stored(db)[1]) == 1


def test_conflicting_original_payload_and_request_version_never_mutate_fact(db, content_safety_event):
    raw = content_safety_event()
    raw.pop("backend_request_id")
    ingest(db, raw)
    for altered in (dict(raw, backend_request_id=None), dict(raw, event_id=str(uuid4()))):
        with pytest.raises(DshContentSafetyConflictError):
            ingest(db, altered)
    assert len(stored(db)[0]) == 1 and stored(db)[0][0].payload_hash == digest(raw)


def test_real_commit_then_lost_observation_returns_no_ack_but_replay_is_idempotent(db, content_safety_event):
    raw = content_safety_event()

    def sessions():
        session = Session(db)
        event.listen(
            session,
            "after_commit",
            lambda _session: (_ for _ in ()).throw(RuntimeError("synthetic lost observation")),
            once=True,
        )
        return session

    with pytest.raises(DshContentSafetyUnavailableError):
        asyncio.run(service(db, sessions).ingest(raw, VerifiedSource(raw["source_id"], 101)))
    assert len(stored(db)[0]) == len(stored(db)[1]) == 1
    assert ingest(db, raw).duplicate and len(stored(db)[0]) == 1


@pytest.mark.parametrize("cleanup_first", [False, True])
def test_missing_sentinel_serializes_native_admission_and_cleanup_watermark(db, content_safety_clock, cleanup_first):
    held, release, waiting, returned = (threading.Event() for _ in range(4))
    contender_thread = []
    cutoff = content_safety_clock.now()
    entered = native(content_safety_clock, started=cutoff - timedelta(days=1))

    def first():
        with transaction(db) as session:
            if cleanup_first:
                row = Settings(session).begin_cleanup(before=cutoff)
                row.mode, row.version = "CONTENT", 7
                session.flush()
            else:
                Writer(session).upsert_request(entered)
            held.set()
            assert release.wait(timeout=5)

    def second():
        assert held.wait(timeout=5)
        contender_thread.append(threading.get_ident())
        with transaction(db) as session:
            if cleanup_first:
                with pytest.raises(ValueError, match="retention watermark"):
                    Writer(session).upsert_request(entered)
            else:
                Settings(session).begin_cleanup(before=cutoff)

    def observe(_connection, _cursor, sql, _parameters, _execution, _many):
        if (
            contender_thread
            and threading.get_ident() == contender_thread[0]
            and "dsh_model_audit_setting" in sql.lower()
        ):
            waiting.set()

    def completed(_connection, _cursor, sql, _parameters, _execution, _many):
        if (
            contender_thread
            and threading.get_ident() == contender_thread[0]
            and "dsh_model_audit_setting" in sql.lower()
        ):
            returned.set()

    event.listen(db, "before_cursor_execute", observe)
    event.listen(db, "after_cursor_execute", completed)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            owner = executor.submit(first)
            try:
                assert held.wait(timeout=5)
                contender = executor.submit(second)
                assert waiting.wait(timeout=5), "Contender must reach an actual setting SQL operation"
                with pytest.raises(FutureTimeoutError):
                    contender.result(timeout=0.1)
                assert not returned.is_set(), "The setting operation must wait for the real owner transaction"
            finally:
                release.set()
            owner.result(timeout=10)
            contender.result(timeout=10)
        assert returned.is_set()
    finally:
        event.remove(db, "before_cursor_execute", observe)
        event.remove(db, "after_cursor_execute", completed)
    with transaction(db) as session:
        row = session.exec(select(Setting)).one()
        assert row.audit_deleted_before == cutoff.replace(tzinfo=None)
        assert (row.mode, row.version) == (("CONTENT", 7) if cleanup_first else ("OFF", 0))
        assert Maintenance(session).purge_batch()["audits_deleted"] == 0
    if cleanup_first:
        assert stored(db)[1] == []
    else:
        assert len(stored(db)[1]) == 1 and stored(db)[1][0].model_result == "RUNNING"

        @contextmanager
        def repository_scope():
            with transaction(db) as session:
                yield Writer(session)

        def no_storage():
            raise AssertionError("Metadata-only completion must never access objects")

        writer = DshModelAuditWriter(repository_scope, no_storage, attempts=1)

        async def complete():
            for kind, facts in (
                (
                    "terminal",
                    {
                        "model_result": "SUCCEEDED",
                        "input_complete": True,
                        "capture_failed": False,
                        "channels": {},
                        "input_units": 1,
                    },
                ),
                ("response", {"response_result": "COMPLETED"}),
                ("usage", {"usage_settlement": "SETTLED"}),
            ):
                assert await writer.write(
                    AuditEvent(
                        request_id=entered.request_id,
                        tenant_id=101,
                        kind=kind,
                        observed_at=cutoff,
                        metadata={**entered.metadata, **facts},
                    )
                )

        asyncio.run(complete())
        with transaction(db) as session:
            assert Maintenance(session).purge_batch()["audits_deleted"] == 1
        assert stored(db)[1] == []


def test_late_committed_unassociated_receipt_cannot_resurrect_below_watermark(
    db, content_safety_event, content_safety_clock
):
    raw = content_safety_event(forwarded=True, backend_request_id=str(uuid4()))
    with transaction(db, 202) as session:
        foreign = Request(
            request_id=raw["backend_request_id"],
            tenant_id=202,
            user_id=22,
            model_id=8,
            session_id=None,
            started_at=content_safety_clock.now(),
        )
        session.add(foreign)
    receipt = ingest(db, raw)
    assert receipt.association_status == "UNASSOCIATED"
    with transaction(db) as session:
        Settings(session).begin_cleanup(before=content_safety_clock.now() + timedelta(seconds=1))
    with transaction(db, 202) as session:
        session.delete(session.get(Request, foreign.request_id))
    assert ingest(db, raw).duplicate and stored(db)[1] == []
    with pytest.raises(DshContentSafetyExpiredError):
        ingest(db, dict(raw, event_id=str(uuid4()), event_version=2))


def test_group_dirty_leases_and_revision_restart_publish_one_consistent_generation(
    db, content_safety_event, content_safety_clock
):
    raw = content_safety_event(
        forwarded=True,
        backend_request_id=str(uuid4()),
        event_kind="DECISION",
        hit_count=0,
        rule_refs=[],
        stage_results={"input": "PASSED", "output": "UNREPORTED"},
        stage_versions={"input": 1, "output": 0},
    )
    receipt = ingest(db, raw)
    with transaction(db) as session:
        repo = Queries(session)
        assert repo.project_request(receipt.audit_request_id)
        repo.fold_hierarchy_batch()
    now = content_safety_clock.now()
    with transaction(db) as session:
        owner = Queries(session).tree_step(now=now)["owner"]
    with transaction(db) as session:
        assert Queries(session).tree_step(now=now)["status"] == "BUSY"
        new_owner = Queries(session).tree_step(now=now + timedelta(seconds=61))["owner"]
    with transaction(db) as session:
        assert Queries(session).tree_step(owner=owner, now=now + timedelta(seconds=61))["status"] == "STALE"
    changed = dict(
        raw,
        event_id=str(uuid4()),
        event_version=2,
        event_kind="FINAL",
        stage_results={"input": "PASSED", "output": "BLOCKED"},
        stage_versions={"input": 1, "output": 2},
        hit_count=1,
        rule_refs=["synthetic-rule"],
        drain_status="FINISHED",
    )
    ingest(db, changed)
    with transaction(db) as session:
        repo = Queries(session)
        assert repo.project_request(receipt.audit_request_id)
        assert repo.tree_step(owner=new_owner, now=now + timedelta(seconds=61))["status"] == "RESTART"
    owner = None
    for _ in range(30):
        with transaction(db) as session:
            result = Queries(session).tree_step(owner=owner, now=now + timedelta(seconds=62))
        owner = result.get("owner")
        if not result["has_more"]:
            break
    else:
        pytest.fail("Finite real-database shadow generation did not converge")
    with transaction(db) as session:
        repo = Queries(session)
        state = repo.tree_state()
        assert state.published_safety_summary_revision == state.safety_summary_revision
        assert repo.tree_progress()["summary_ready"]
        assert repo.group_page()["items"][0]["sensitive_hit_count"] == 1
        assert not repo.project_request(receipt.audit_request_id)


def test_real_details_only_keeps_hit_and_purged_status_without_consuming_main_checkpoint(
    db, content_safety_event, content_safety_clock, content_safety_identities
):
    cutoff = content_safety_clock.now() + timedelta(seconds=1)
    ingest(db, content_safety_event(request_started_at=(cutoff - timedelta(seconds=5)).isoformat()))
    target = ingest(db, content_safety_event())
    ingest(db, content_safety_event(identity=content_safety_identities[1]))
    with transaction(db) as session:
        Settings(session).begin_cleanup(before=cutoff)
    with transaction(db) as session:
        assert Maintenance(session).purge_batch(limit=1)["audits_deleted"] == 1
    with transaction(db) as session:
        checkpoint = session.exec(select(Setting)).one().model_dump()
        assert checkpoint["cleanup_after_request_id"] is not None
        audit = session.get(Request, target.audit_request_id).model_dump()
    with transaction(db) as session:
        result = Maintenance(session).purge_batch(
            details_before=datetime.now(UTC) + timedelta(seconds=1), include_audits=False, limit=1
        )
        assert result == {"details_deleted": 1, "audits_deleted": 0, "has_more": False}
    with transaction(db) as session:
        assert session.exec(select(Setting)).one().model_dump() == checkpoint
        row = session.get(Request, target.audit_request_id)
        assert row.model_dump() == audit and row.has_sensitive_hit
        assert ContentSafetyQueryRepository(session).request_events(row.request_id)["details_status"] == "PURGED"
    assert len(stored(db, 202)[0]) == len(stored(db, 202)[1]) == 1
    with transaction(db) as session:
        assert Maintenance(session).purge_batch()["audits_deleted"] == 1
    assert stored(db) == ([], []) and len(stored(db, 202)[0]) == 1
