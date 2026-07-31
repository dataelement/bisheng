"""F048 DDL-only revision and disposable MySQL/DM8 schema contract.

Local/default runs prove the revision contains no business-data migration.
An environment integration run sets ``F048_DATABASE_INTEGRATION=1`` plus both
``F048_MYSQL_TEST_DSN`` and ``F048_DM8_TEST_DSN``.  Each DSN must point at a
fresh, disposable schema whose name contains ``f048_test`` and the job must set
``F048_DATABASE_EPHEMERAL_ACK=1``.  The test never drops or rewrites an existing
F048 table.  It validates schema, cursor, CAS, uniqueness, and checkpoint
contracts; coordinator/runtime/verifier/CLI tests cover the formal data
migration logic without claiming that this file executes that CLI.

覆盖 AC: AC-93, AC-94, AC-95, AC-96, AC-98, AC-104, AC-105, AC-106,
AC-117, AC-137, AC-138, AC-139, AC-140, AC-146, AC-147, AC-158
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.ddl.impl import DefaultImpl
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection, Engine, make_url

from bisheng.core.database.alembic.versions import (
    f048_permission_model_grants as revision,
)

REVISION_PATH = Path(revision.__file__)
F048_TABLES = (
    "authorization_model_release",
    "permission_catalog_release",
    "permission_action",
    "permission_action_resource_scope",
    "permission_model",
    "permission_model_action",
    "permission_catalog_projection_tuple",
    "permission_projection_operation",
    "permission_projection_tuple",
    "permission_grant",
    "permission_grant_assignee",
    "resource_permission_mode",
    "permission_migration_run",
    "permission_migration_item",
)
LIVE_ENABLED = os.environ.get("F048_DATABASE_INTEGRATION") == "1"
_DML = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|MERGE)\s", re.IGNORECASE)


def test_alembic_revision_is_schema_only() -> None:
    source = REVISION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert imported_modules <= {
        "collections.abc",
        "alembic",
        "bisheng.core.database.alembic_helpers.online",
    }
    assert not _DML.search(source)
    assert "session" not in {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert revision.revision == "f048_permission_grants"
    assert revision.down_revision == "f044_llm_status_time"


def test_revision_declares_expected_schema_and_resume_constraints() -> None:
    source = REVISION_PATH.read_text(encoding="utf-8")
    for table in F048_TABLES:
        assert f'"{table}"' in source
    for constraint in (
        "uq_auth_model_release",
        "uq_perm_catalog_version",
        "uq_perm_grant_resource_model",
        "uq_perm_assignee_source",
        "uq_resource_permission_mode",
        "uq_perm_migration_environment",
        "uq_perm_migration_item_source",
        "ix_perm_migration_item_resume",
    ):
        assert constraint in source
    assert "dashboard" in source
    assert "tenant_id" in source


def _require_live_dsn(env_key: str, dialect_name: str) -> str:
    if os.environ.get("F048_DATABASE_EPHEMERAL_ACK") != "1":
        pytest.fail("F048_DATABASE_EPHEMERAL_ACK=1 is required for live database tests")
    dsn = os.environ.get(env_key)
    if not dsn:
        pytest.fail(f"{env_key} is required when F048_DATABASE_INTEGRATION=1")
    url = make_url(dsn)
    if url.get_backend_name() != dialect_name:
        pytest.fail(f"{env_key} must use the {dialect_name} SQLAlchemy dialect")
    marker = os.environ.get("F048_DATABASE_SCHEMA_MARKER", "f048_test").casefold()
    safe_identity = "|".join(
        str(value or "")
        for value in (
            url.database,
            url.username,
            url.query.get("schema"),
        )
    ).casefold()
    if marker not in safe_identity:
        pytest.fail(f"{env_key} must target a disposable schema containing {marker!r}")
    return dsn


def _register_dm_alembic_impl() -> None:
    class F048DMIntegrationImpl(DefaultImpl):
        __dialect__ = "dm"
        transactional_ddl = False


def _apply_revision(
    connection: Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if connection.dialect.name == "dm":
        _register_dm_alembic_impl()
    operations = Operations(MigrationContext.configure(connection))
    inspector = sa.inspect(connection)
    monkeypatch.setattr(revision, "op", operations)
    monkeypatch.setattr(
        revision,
        "table_exists",
        lambda table: inspector.has_table(table),
    )
    monkeypatch.setattr(
        revision,
        "column_exists",
        lambda table, column: any(item["name"] == column for item in inspector.get_columns(table)),
    )
    monkeypatch.setattr(
        revision,
        "index_exists",
        lambda table, index: any(item["name"] == index for item in inspector.get_indexes(table)),
    )
    revision.upgrade()


def _assert_schema(engine: Engine) -> None:
    inspector = sa.inspect(engine)
    assert set(F048_TABLES).issubset(inspector.get_table_names())
    expected_uniques = {
        "permission_grant": {"uq_perm_grant_resource_model"},
        "permission_grant_assignee": {"uq_perm_assignee_source"},
        "resource_permission_mode": {"uq_resource_permission_mode"},
        "permission_migration_run": {"uq_perm_migration_environment"},
        "permission_migration_item": {"uq_perm_migration_item_source"},
    }
    for table, required in expected_uniques.items():
        names = {str(item.get("name")) for item in inspector.get_unique_constraints(table)}
        assert required.issubset(names)
    resume_indexes = {str(item.get("name")) for item in inspector.get_indexes("permission_migration_item")}
    assert "ix_perm_migration_item_resume" in resume_indexes


def _exercise_checkpoint_contract(engine: Engine) -> None:
    metadata = sa.MetaData()
    run = sa.Table("permission_migration_run", metadata, autoload_with=engine)
    item = sa.Table("permission_migration_item", metadata, autoload_with=engine)
    fingerprint = "1" * 64
    source_checksum = "2" * 64
    target_checksum = "3" * 64

    with engine.begin() as connection:
        connection.execute(
            run.insert().values(
                environment_fingerprint=fingerprint,
                phase="WRITING_TARGET",
                status="RUNNING",
                store_id="store-same",
                source_model_id="model-old",
                target_model_id="model-f048",
                source_watermark="watermark-1",
                checkpoint="0",
                source_checksum=source_checksum,
                lock_token="worker-1",
            )
        )
        run_id = connection.execute(
            sa.select(run.c.id).where(run.c.environment_fingerprint == fingerprint)
        ).scalar_one()
        connection.execute(
            item.insert(),
            [
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "source_kind": "RESOURCE",
                    "source_locator": f"workflow:{index}",
                    "source_checksum": checksum,
                    "target_kind": "GRANT",
                    "target_id": str(index),
                    "target_checksum": target_checksum,
                    "status": "PENDING",
                    "severity": "INFO",
                }
                for index, tenant_id, checksum in (
                    (1, 1, "a" * 64),
                    (2, 1, "b" * 64),
                    (3, 2, "c" * 64),
                )
            ],
        )

    with engine.begin() as connection:
        first_page = connection.execute(
            sa.select(item.c.id, item.c.tenant_id, item.c.source_locator)
            .where(item.c.run_id == run_id, item.c.id > 0)
            .order_by(item.c.id)
            .limit(2)
        ).all()
        assert len(first_page) == 2
        checkpoint = first_page[-1].id
        second_page = (
            connection.execute(
                sa.select(item.c.id).where(item.c.run_id == run_id, item.c.id > checkpoint).order_by(item.c.id).limit(2)
            )
            .scalars()
            .all()
        )
        assert len(second_page) == 1
        assert not {row.id for row in first_page}.intersection(second_page)

        updated = connection.execute(
            run.update().where(run.c.id == run_id, run.c.version == 1).values(checkpoint=str(checkpoint), version=2)
        )
        assert updated.rowcount == 1
        stale = connection.execute(
            run.update().where(run.c.id == run_id, run.c.version == 1).values(checkpoint="stale", version=2)
        )
        assert stale.rowcount == 0

        connection.execute(
            item.update().where(item.c.run_id == run_id).values(status="VERIFIED", target_checksum=target_checksum)
        )
        finalized = connection.execute(
            run.update()
            .where(run.c.id == run_id, run.c.version == 2)
            .values(
                phase="READY_TO_START",
                status="COMPLETED",
                target_checksum=target_checksum,
                checkpoint=str(second_page[-1]),
                version=3,
            )
        )
        assert finalized.rowcount == 1

    with engine.connect() as connection:
        state = connection.execute(
            sa.select(
                run.c.phase,
                run.c.status,
                run.c.source_checksum,
                run.c.target_checksum,
                run.c.version,
            ).where(run.c.id == run_id)
        ).one()
        assert state == (
            "READY_TO_START",
            "COMPLETED",
            source_checksum,
            target_checksum,
            3,
        )
        assert (
            connection.execute(
                sa.select(sa.func.count())
                .select_from(item)
                .where(
                    item.c.run_id == run_id,
                    item.c.status == "VERIFIED",
                    item.c.target_checksum == target_checksum,
                )
            ).scalar_one()
            == 3
        )

    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                item.insert().values(
                    run_id=run_id,
                    tenant_id=1,
                    source_kind="RESOURCE",
                    source_locator="workflow:1",
                    source_checksum="d" * 64,
                    status="PENDING",
                    severity="INFO",
                )
            )


def _run_live_contract(
    *,
    dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine(dsn, pool_pre_ping=True)
    try:
        existing = set(sa.inspect(engine).get_table_names()).intersection(F048_TABLES)
        assert not existing, f"live F048 database contract requires a fresh schema; existing={sorted(existing)}"
        with engine.begin() as connection:
            _apply_revision(connection, monkeypatch)
        _assert_schema(engine)
        _exercise_checkpoint_contract(engine)
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="set F048_DATABASE_INTEGRATION=1 for disposable MySQL/DM8 tests",
)
def test_disposable_mysql_schema_and_checkpoint_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_live_contract(
        dsn=_require_live_dsn("F048_MYSQL_TEST_DSN", "mysql"),
        monkeypatch=monkeypatch,
    )


@pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="set F048_DATABASE_INTEGRATION=1 for disposable MySQL/DM8 tests",
)
def test_disposable_dm8_schema_and_checkpoint_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_live_contract(
        dsn=_require_live_dsn("F048_DM8_TEST_DSN", "dm"),
        monkeypatch=monkeypatch,
    )
