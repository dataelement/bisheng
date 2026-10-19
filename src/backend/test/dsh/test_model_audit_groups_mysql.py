"""Opt-in disposable local MySQL validation, never a configured business database.

DSH_AUDIT_GROUPS_MYSQL=1 pytest test/dsh/test_model_audit_groups_mysql.py -q
Only the uniquely named, locally created test container is removed on exit.
"""

import importlib.util
import os
import secrets
import subprocess
import time
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from bisheng.dsh.domain.models.model_audit_conversation import DshModelAuditConversation
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
from test.dsh.model_audit_fixtures import NOW, audit_database, audit_session
from test.dsh.test_model_audit_groups import row


@pytest.mark.skipif(os.environ.get("DSH_AUDIT_GROUPS_MYSQL") != "1", reason="Explicit local Docker opt-in required")
def test_owned_mysql_upgrade_projection_and_exact_query_plan():
    """AC-QC-09/11: actual DDL, transaction retry and indexed equality on MySQL."""
    endpoint = subprocess.check_output(
        ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], text=True
    ).strip()
    assert endpoint.startswith("unix://"), "Only a local test Docker engine is permitted"
    name = "e2e-dsh-audit-groups-" + secrets.token_hex(6)
    password = secrets.token_hex(24)
    command = [
        "docker",
        "run",
        "-d",
        "--pull=never",
        "--name",
        name,
        "--label",
        "bisheng.test=dsh-audit-groups",
        "-p",
        "127.0.0.1::3306",
        "-e",
        "MYSQL_ROOT_PASSWORD=" + password,
        "-e",
        "MYSQL_DATABASE=dsh_test_audit_groups",
        "mysql:8.0",
    ]
    started = subprocess.run(command, capture_output=True, timeout=30)
    assert started.returncode == 0, "Could not start isolated MySQL fixture"
    engine = None
    try:
        port = int(subprocess.check_output(["docker", "port", name, "3306"], text=True).strip().split(":")[-1])
        engine = sa.create_engine(
            f"mysql+pymysql://root:{password}@127.0.0.1:{port}/dsh_test_audit_groups",
            hide_parameters=True,
            pool_pre_ping=True,
        )
        for attempt in range(160):
            try:
                with engine.connect() as connection:
                    connection.execute(sa.text("SELECT 1"))
                break
            except sa.exc.OperationalError:
                if attempt == 159:
                    raise RuntimeError("Isolated MySQL did not become ready") from None
                time.sleep(0.25)
        fields = {"audit_status", "group_index_pending", "group_indexed_status"}
        legacy = sa.Table(
            "dsh_model_audit_request",
            sa.MetaData(),
            *[column._copy() for column in DshModelAuditRequest.__table__.columns if column.name not in fields],
        )
        path = Path(__file__).resolve().parents[2] / "bisheng/core/database/alembic/versions/v3_0_0_dsh_audit_groups.py"
        spec = importlib.util.spec_from_file_location("audit_group_upgrade", path)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        with engine.begin() as connection:
            legacy.create(connection)
            DshModelAuditConversation.__table__.create(connection)
            with Operations.context(MigrationContext.configure(connection)):
                revision.upgrade()
                revision.upgrade()
            assert fields <= {c["name"] for c in sa.inspect(connection).get_columns(legacy.name)}
            indexes = {index["name"] for index in sa.inspect(connection).get_indexes(legacy.name)}
            assert {"ix_dma_request_status", "ix_dma_request_association", "ix_dma_request_group_pending"} <= indexes
        # Reuse the fixture's scoped listener registration and teardown, not its SQLite data.
        with audit_database():
            with audit_session(engine) as session, session.begin():
                session.add(row("e2e-mysql-one", model_result="FAILED"))
            with audit_session(engine) as session:
                repository = DshModelAuditQueryRepository(session)
                repository.project_request("e2e-mysql-one", now=NOW)
                session.rollback()
            with audit_session(engine) as session, session.begin():
                repository = DshModelAuditQueryRepository(session)
                assert repository.project_request("e2e-mysql-one", now=NOW)
                assert not repository.project_request("e2e-mysql-one", now=NOW)
            with audit_session(engine) as session:
                page = DshModelAuditQueryRepository(session).group_page(
                    audit_status="ABNORMAL", model_name="Provider / A"
                )
                assert len(page["items"]) == 1 and page["items"][0]["abnormal_count"] == 1
                plan = (
                    session.execute(
                        sa.text(
                            "EXPLAIN SELECT request_id FROM dsh_model_audit_request WHERE tenant_id=:tenant AND audit_status=:status ORDER BY started_at,request_id LIMIT 20"
                        ),
                        {"tenant": 2, "status": "ABNORMAL"},
                    )
                    .mappings()
                    .all()
                )
                assert "ix_dma_request_status" in str(plan)
    finally:
        if engine is not None:
            engine.dispose()
        subprocess.run(["docker", "rm", "-f", "-v", name], check=True, stdout=subprocess.DEVNULL)
