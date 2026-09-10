"""T046: Coverage AC: AC-22, AC-23, AC-24, AC-30, AC-34."""

import os
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import make_url
from sqlmodel import Session, SQLModel

from bisheng.core.context.tenant import current_tenant_id
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.usage import DshUsageRepository, UsageEvent


def event(user=20, **changes):
    values = {
        "request_id": str(uuid4()),
        "tenant_id": 2,
        "user_id": user,
        "seat_id": str(uuid4()),
        "session_id": str(uuid4()),
        "grant_version": 1,
        "model_id": 4,
        "usage_month": "2026-09",
        "policy_version": 1,
        "event_version": 1,
        "quota_epoch": 1,
        "billing_timezone": "Asia/Shanghai",
        "started_at": datetime(2026, 9, 9),
        "status": "RUNNING",
    }
    values.update(changes)
    return UsageEvent(**values)


@pytest.fixture
def usage_db():
    url = os.environ.get("DSH_TEST_DATABASE_URL", "sqlite://")
    if url != "sqlite://":
        parsed = make_url(url)
        if (
            os.environ.get("DSH_TEST_DATABASE_ISOLATED") != "1"
            or not parsed.database
            or not parsed.database.startswith("dsh_test_")
        ):
            raise ValueError("External tests require an explicitly isolated dsh_test_ database")
    engine = create_engine(url)
    tables = [DshUserPolicy.__table__, DshModelCall.__table__, DshMonthlyUsage.__table__]
    if any(inspect(engine).has_table(table.name) for table in tables):
        raise ValueError("Refusing to modify pre-existing DSH test tables")
    SQLModel.metadata.create_all(
        engine, tables=[DshUserPolicy.__table__, DshModelCall.__table__, DshMonthlyUsage.__table__]
    )
    token = current_tenant_id.set(2)
    with Session(engine) as session:
        session.add_all([DshUserPolicy(model_id=4, enabled=1, tenant_id=2, user_id=u, updated_by=1) for u in (20, 21)])
        session.commit()
    yield engine
    current_tenant_id.reset(token)
    # Only remove the three tables whose absence was proved before this fixture created them.
    SQLModel.metadata.drop_all(engine, tables=list(reversed(tables)))
    engine.dispose()


def test_terminal_first_duplicate_batch_and_distinct_users(usage_db):
    running = event()
    terminal = running.model_copy(
        update={
            "event_version": 2,
            "status": "SUCCEEDED",
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
            "usage_source": "PROVIDER",
        }
    )
    second = event(21, status="SUCCEEDED", input_tokens=1, output_tokens=2, total_tokens=3, usage_source="PROVIDER")
    with Session(usage_db) as session, session.begin():
        assert DshUsageRepository(session).project_batch([terminal, running, second]) == 2
    with Session(usage_db) as session, session.begin():
        assert DshUsageRepository(session).project_batch([running, terminal, second]) == 0
        assert sorted(r.used_tokens for r in session.scalars(select(DshMonthlyUsage))) == [3, 30]


def test_unknown_then_reliable_preserves_month_and_rejects_overwrite(usage_db):
    unknown = event(status="USAGE_UNKNOWN", usage_month="2026-08")
    settled = unknown.model_copy(
        update={
            "event_version": 2,
            "status": "FAILED",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "usage_source": "RECONCILED",
        }
    )
    with Session(usage_db) as session, session.begin():
        repo = DshUsageRepository(session)
        repo.project_batch([unknown])
        assert session.get(DshModelCall, unknown.request_id).total_tokens is None
        repo.project_batch([settled])
        assert session.get(DshModelCall, unknown.request_id).total_tokens == 0
        assert next(iter(session.scalars(select(DshMonthlyUsage)))).usage_month == "2026-08"
        with pytest.raises(ValueError):
            repo.project_batch(
                [
                    settled.model_copy(
                        update={"event_version": 3, "total_tokens": 3, "input_tokens": 1, "output_tokens": 2}
                    )
                ]
            )


def test_batch_transaction_rolls_back_and_tenant_is_verified(usage_db):
    first = event(status="SUCCEEDED", input_tokens=1, output_tokens=2, total_tokens=3, usage_source="PROVIDER")
    with Session(usage_db) as session:
        with pytest.raises(ValueError), session.begin():
            DshUsageRepository(session).project_batch([first, event(tenant_id=3)])
    with Session(usage_db) as session:
        assert session.get(DshModelCall, first.request_id) is None


def test_concurrent_first_month_is_serialized_by_existing_policy(usage_db):
    if usage_db.dialect.name == "sqlite":
        pytest.skip("Row-lock concurrency is exercised on the isolated MySQL database")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)
    events = [
        event(status="SUCCEEDED", input_tokens=3, output_tokens=7, total_tokens=10, usage_source="PROVIDER")
        for _ in range(2)
    ]

    def project(item):
        token = current_tenant_id.set(2)
        try:
            barrier.wait(timeout=10)
            with Session(usage_db) as session, session.begin():
                return DshUsageRepository(session).project_batch([item])
        finally:
            current_tenant_id.reset(token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(project, events)) == [1, 1]
    with Session(usage_db) as session:
        rows = list(session.scalars(select(DshMonthlyUsage)))
        assert len(rows) == 1 and rows[0].used_tokens == 20


def test_persisted_usage_estimate_counts_cross_month_unknown_without_leaking_users(usage_db):
    september = event(status="SUCCEEDED", input_tokens=3, output_tokens=4, total_tokens=7, usage_source="PROVIDER")
    august_unknown = event(usage_month="2026-08", started_at=datetime(2026, 8, 31), status="USAGE_UNKNOWN")
    another_user = event(21, status="USAGE_UNKNOWN")
    with Session(usage_db) as session, session.begin():
        DshUsageRepository(session).project_batch([september, august_unknown, another_user])
    with Session(usage_db) as session, session.begin():
        snapshot = DshUsageRepository(session).persisted_usage(20, "2026-09")
        assert snapshot["used"] == 7
        assert snapshot["unknown_pending"] == 1
        assert snapshot["source"] == "sql_estimate"
        assert snapshot["quota_state"] == "unavailable"


def test_recovery_epoch_cas_rejects_concurrently_changed_policy(usage_db):
    with Session(usage_db) as session, session.begin():
        _, original = DshUsageRepository(session).recovery_snapshot(20, billing_timezone="UTC")
    with Session(usage_db) as session, session.begin():
        policy = session.scalar(select(DshUserPolicy).where(DshUserPolicy.user_id == 20))
        policy.version = 1
    with pytest.raises(ValueError, match="SQL policy changed"), Session(usage_db) as session, session.begin():
        DshUsageRepository(session).complete_recovery(20, expected_policy=original, epoch=2)
    with Session(usage_db) as session, session.begin():
        policy = session.scalar(select(DshUserPolicy).where(DshUserPolicy.user_id == 20))
        assert policy.quota_epoch == 1
