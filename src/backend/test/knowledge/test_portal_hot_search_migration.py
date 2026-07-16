import importlib
from datetime import datetime

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from bisheng.knowledge.domain.models.portal_hot_search_snapshot import (
    PortalHotSearchBatchRun,
    PortalHotSearchCandidate,
    PortalHotSearchSnapshot,
)

MIGRATION_MODULE = "bisheng.core.database.alembic.versions.v2_5_0_sg_048_portal_hot_search"

_TABLES = (
    "portal_hot_search_snapshot",
    "portal_hot_search_batch_run",
    "portal_hot_search_candidate",
)


def _run(operation: str, engine: sa.Engine) -> None:
    migration = importlib.import_module(MIGRATION_MODULE)
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            getattr(migration, operation)()


def test_revision_chains_onto_portal_recommendation_head():
    migration = importlib.import_module(MIGRATION_MODULE)

    assert migration.revision == "v2_5_0_sg_048_portal_hot_search"
    assert migration.down_revision == "v2_5_0_sg_f056_portal_recommendation"


def test_upgrade_creates_three_tables_with_columns_and_indexes_then_downgrades():
    engine = sa.create_engine("sqlite://")

    _run("upgrade", engine)
    inspector = sa.inspect(engine)

    for table in _TABLES:
        assert table in inspector.get_table_names()

    snapshot_columns = {c["name"] for c in inspector.get_columns("portal_hot_search_snapshot")}
    assert snapshot_columns == {
        "id",
        "tenant_id",
        "rank_no",
        "intent_key",
        "display_query",
        "canonical_query",
        "heat_score",
        "unique_users",
        "search_count_7d",
        "search_count_8_30d",
        "batch_id",
        "computed_at",
        "create_time",
    }

    batch_run_columns = {c["name"] for c in inspector.get_columns("portal_hot_search_batch_run")}
    assert {"status", "window_start", "window_end", "llm_degraded", "truncated", "error_message"} <= batch_run_columns

    candidate_columns = {c["name"] for c in inspector.get_columns("portal_hot_search_candidate")}
    assert {"member_queries", "final_rank", "rewrite_source", "llm_sample", "qualified"} <= candidate_columns

    snapshot_indexes = {tuple(i["column_names"]) for i in inspector.get_indexes("portal_hot_search_snapshot")}
    assert ("tenant_id", "batch_id") in snapshot_indexes
    assert ("tenant_id", "rank_no") in snapshot_indexes

    batch_run_indexes = {tuple(i["column_names"]) for i in inspector.get_indexes("portal_hot_search_batch_run")}
    assert ("tenant_id", "computed_at") in batch_run_indexes
    assert ("tenant_id", "batch_id") in batch_run_indexes

    candidate_indexes = {tuple(i["column_names"]) for i in inspector.get_indexes("portal_hot_search_candidate")}
    assert ("tenant_id", "batch_id") in candidate_indexes

    _run("downgrade", engine)
    remaining = set(sa.inspect(engine).get_table_names())
    assert not (remaining & set(_TABLES))


def test_upgrade_is_idempotent():
    engine = sa.create_engine("sqlite://")

    _run("upgrade", engine)
    _run("upgrade", engine)

    table_names = set(sa.inspect(engine).get_table_names())
    assert set(_TABLES) <= table_names


def test_full_upgrade_downgrade_cycle_and_repeated_downgrade_are_safe():
    engine = sa.create_engine("sqlite://")

    _run("upgrade", engine)
    _run("downgrade", engine)
    _run("downgrade", engine)
    _run("upgrade", engine)

    table_names = set(sa.inspect(engine).get_table_names())
    assert set(_TABLES) <= table_names


def test_orm_defaults_leave_tenant_for_before_flush_and_lengths_match():
    snapshot = PortalHotSearchSnapshot(
        rank_no=1,
        intent_key="k1",
        display_query="设备检修安全要求有哪些？",
        canonical_query="设备检修安全要求",
        batch_id="20260716-01",
        computed_at=datetime(2026, 7, 16),
    )
    assert snapshot.tenant_id is None
    assert snapshot.heat_score == 0
    assert PortalHotSearchSnapshot.__table__.c.intent_key.type.length == 64
    assert PortalHotSearchSnapshot.__table__.c.display_query.type.length == 100

    run = PortalHotSearchBatchRun(
        batch_id="20260716-01",
        status="running",
        window_start=datetime(2026, 6, 16),
        window_end=datetime(2026, 7, 16),
        computed_at=datetime(2026, 7, 16),
    )
    assert run.tenant_id is None
    assert run.llm_degraded == 0
    assert run.truncated == 0

    candidate = PortalHotSearchCandidate(
        batch_id="20260716-01",
        intent_key="k1",
        canonical_query="设备检修安全要求",
        computed_at=datetime(2026, 7, 16),
    )
    assert candidate.tenant_id is None
    assert candidate.final_rank is None
    assert candidate.qualified == 0
