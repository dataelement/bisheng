"""Opt-in disposable local MySQL validation, never a configured business database.

DSH_AUDIT_GROUPS_MYSQL=1 pytest test/dsh/test_model_audit_groups_mysql.py -q
Only the uniquely named, locally created test container is removed on exit.
"""

import asyncio
import os
import secrets
import subprocess
import time

import pytest
import sqlalchemy as sa

from bisheng.dsh.domain.models.model_audit_conversation import DshModelAuditConversation
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
from bisheng.user.domain.models.user import User
from test.dsh.model_audit_fixtures import AUDIT_MODELS, NOW, FaultAuditObjects, audit_database, audit_session
from test.dsh.test_model_audit_groups import row


@pytest.mark.skipif(os.environ.get("DSH_AUDIT_GROUPS_MYSQL") != "1", reason="Explicit local Docker opt-in required")
def test_owned_mysql_bootstrap_projection_and_exact_query_plan():
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
        from bisheng.core.database.alembic_helpers.online import create_missing_model_tables

        with engine.begin() as connection:
            metadata = sa.MetaData()
            for model in (*AUDIT_MODELS, User):
                model.__table__.to_metadata(metadata)
            assert create_missing_model_tables(connection, metadata)
            assert create_missing_model_tables(connection, metadata) == ()
            inspector = sa.inspect(connection)
            assert {"audit_status", "group_index_pending", "group_indexed_status", "hierarchy_indexed"} <= {
                column["name"] for column in inspector.get_columns(DshModelAuditRequest.__tablename__)
            }
            assert {"origin_state", "declared_parent_key", "parent_declaration_missing", "relation_conflict"} <= {
                column["name"] for column in inspector.get_columns(DshModelAuditConversation.__tablename__)
            }
            assert {"ix_dma_request_status", "ix_dma_request_association", "ix_dma_request_group_pending"} <= {
                index["name"] for index in inspector.get_indexes(DshModelAuditRequest.__tablename__)
            }
        # Reuse the fixture's scoped listener registration and teardown, not its SQLite data.
        with audit_database():
            from sqlmodel import SQLModel

            SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in AUDIT_MODELS])
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
            asyncio.run(validate_deferred_bodies(engine))
            validate_tree(engine)
    finally:
        if engine is not None:
            engine.dispose()
        subprocess.run(["docker", "rm", "-f", "-v", name], check=True, stdout=subprocess.DEVNULL)


def validate_tree(engine):
    """AC-H01/H02/H05/H07: actual committed checkpoints and nested indexed lookups."""
    from test.dsh.test_model_audit_tree import add

    with audit_session(engine) as session, session.begin():
        add(session, "mysql-parent", "e2e-mysql-parent")
        add(
            session,
            "mysql-child",
            "e2e-mysql-child",
            origin="subagent",
            parent="e2e-mysql-parent",
            model_result="FAILED",
            name="e2e-tree / mysql-model",
        )
    for _ in range(20):
        with audit_session(engine) as session, session.begin():
            result = DshModelAuditQueryRepository(session).fold_hierarchy_batch()
        if not result["has_more"]:
            break
    owner = None
    for _ in range(100):
        with audit_session(engine) as session, session.begin():
            result = DshModelAuditQueryRepository(session).tree_step(owner=owner)
        owner = result.get("owner")
        if not result["has_more"]:
            break
    with audit_session(engine) as session:
        repo = DshModelAuditQueryRepository(session)
        parents = repo.tree_page(model_name="e2e-tree / mysql-model", audit_status="ABNORMAL")
        assert len(parents["items"]) == 1
        parent = parents["items"][0]
        assert parent["conversation_id"] == "e2e-mysql-parent"
        assert parent["branch_summary"]["abnormal_count"] == 1
        children = repo.tree_page(parent_key=parent["conversation_key"], generation=parent["generation"])
        assert [c["conversation_id"] for c in children["items"]] == ["e2e-mysql-child"]
        plan = (
            session.execute(
                sa.text(
                    "EXPLAIN SELECT conversation_key FROM dsh_audit_tree_node WHERE tenant_id=:tenant AND generation=:generation AND parent_key=:parent ORDER BY listed_at DESC,conversation_key DESC LIMIT 20"
                ),
                {"tenant": 2, "generation": parent["generation"], "parent": parent["conversation_key"]},
            )
            .mappings()
            .all()
        )
        assert "ix_dat_parent" in str(plan)


async def validate_deferred_bodies(engine):
    """AC-17, AC-35, AC-38: actual concurrent SQL consumers, bounded batches and replay."""
    from sqlmodel import SQLModel

    from bisheng.dsh.domain.services.model_audit_capture import AuditCapture
    from bisheng.dsh.infrastructure.model_audit_queue import BoundedAuditQueue
    from test.dsh.test_model_audit_deferred_body import drain
    from test.dsh.test_model_audit_writer import writer_for

    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in AUDIT_MODELS])
    writer = writer_for(engine, FaultAuditObjects())
    writer.attempts = 3
    persist, sizes = writer._persist_bodies, []

    def retry_once(verified):
        sizes.append(len(verified))
        if len(sizes) == 1:
            raise OSError("e2e-dsh-audit-synthetic-transaction-failure")
        persist(verified)

    writer._persist_bodies = retry_once

    async def replay(buffer):
        await writer.write_body_batch(buffer)
        await writer.write_body_batch(buffer)

    queue = BoundedAuditQueue(max_events=10, max_bytes=65536, consumer=writer.write, body_consumer=replay)
    try:
        capture = AuditCapture(
            {
                "request_id": "e2e-dsh-audit-deferred-mysql",
                "tenant_id": 2,
                "user_id": 20,
                "session_id": "e2e-dsh-audit-session",
                "model_id": 42,
                "conversation_id": "e2e-dsh-audit-deferred",
                "effective_mode": "CONTENT",
                "started_at": NOW,
            },
            queue,
            now=lambda: NOW,
            chunk_bytes=64,
            request_budget_bytes=65536,
            digest_key=bytes(range(32)),
            key_version="test-key",
        )
        capture.entered([{"role": "user", "content": "e2e-dsh-audit-" * 300}])
        capture.output({"delta": {"content": "e2e-dsh-audit-reply"}})
        capture.terminal("SUCCEEDED")
        capture.response("COMPLETED")
        capture.usage("SETTLED")
        await drain(queue)
        assert writer.failed == 0 and sizes and max(sizes) == 32
        with audit_session(engine) as session:
            from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository

            repo = DshModelAuditWriteRepository(session)
            row = repo.request("e2e-dsh-audit-deferred-mysql")
            manifest, occurrences, _ = repo.facts(row.request_id)
            assert row.content_status == "COMPLETE" and row.audit_status == "NORMAL"
            assert len(occurrences) == sum(channel["count"] for channel in manifest.channels.values())
    finally:
        await queue.close(1)
