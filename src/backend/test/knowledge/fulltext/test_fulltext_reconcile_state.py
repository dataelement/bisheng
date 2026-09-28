from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.contracts.fulltext_reconcile import ReconcileSourceRelationError
from bisheng.knowledge.domain.models.knowledge_fulltext_reconcile import FulltextReconcileIssue, FulltextReconcileRun
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_reconcile_state_repository_impl import (
    FulltextReconcileStateRepository,
)


@pytest.fixture
async def state_session():
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: KnowledgeFile.__table__.create(c))
        await conn.run_sync(lambda c: FulltextReconcileRun.__table__.create(c))
        await conn.run_sync(lambda c: FulltextReconcileIssue.__table__.create(c))
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


async def test_source_failure_survives_new_round_and_only_verified_success_resolves(state_session):
    repo = FulltextReconcileStateRepository(state_session)
    now = datetime(2026, 9, 28)
    error = ReconcileSourceRelationError("document_missing", "same-source")
    for day in range(2):
        current = now + timedelta(days=day)
        run = await repo.load_or_create(current, 13)
        failures = await repo.record_source_failures({13: error}, current)
        await repo.checkpoint(run.id, "forward", 13, failures, {}, current)
        assert await repo.finish_scan(run.id, current) == "completed_with_errors"
    issue = await state_session.get(FulltextReconcileIssue, ("source", 13))
    assert issue.status == "blocked"
    assert issue.attempts == 1
    # 反向看到记录存在或仅关系修复，都不能冒充全文写入已验证。
    await repo.checkpoint(run.id, "reverse", 13, {}, {13: "reverse_existing"}, current)
    assert issue.status == "blocked"
    await repo.checkpoint(run.id, "retry", 13, {}, {13: "repaired"}, current)
    await state_session.refresh(issue)
    assert issue.status == "resolved"


async def test_transient_source_budget_is_bounded_across_rounds_and_resets_only_on_change(state_session):
    repo = FulltextReconcileStateRepository(state_session)
    now = datetime(2026, 9, 28)
    error = ReconcileSourceRelationError("primary_version_unset", "v1", retryable=True)
    for attempt in range(8):
        await repo.record_source_failures({13: error}, now + timedelta(hours=attempt))
    issue = await state_session.get(FulltextReconcileIssue, ("source", 13))
    assert issue.status == "blocked"
    assert issue.attempts == 8
    await repo.record_source_failures({13: error}, now + timedelta(days=1))
    assert issue.attempts == 8
    changed = ReconcileSourceRelationError("primary_version_missing", "v2", retryable=True)
    await repo.record_source_failures({13: changed}, now + timedelta(days=1))
    assert issue.status == "pending"
    assert issue.attempts == 1
    await repo.record_source_failures({13: changed}, now + timedelta(days=1, seconds=1))
    assert issue.attempts == 1


async def test_checkpoint_records_failure_before_advancing_and_resumes_same_run(state_session):
    repo = FulltextReconcileStateRepository(state_session)
    now = datetime(2026, 9, 17, 1)
    run = await repo.load_or_create(now, 900)
    await repo.checkpoint(run.id, "forward", 200, {3: "read_failed"}, {1: "consistent"}, now)
    await state_session.commit()
    resumed = await repo.load_or_create(now + timedelta(days=1), 1000)
    assert resumed.id == run.id
    assert resumed.cursor == 200
    assert resumed.upper_id == 900
    failures = await repo.due(run.id, now + timedelta(minutes=10))
    assert [i.file_id for i in failures] == [3]


async def test_same_source_repair_is_not_reset_by_new_scan_or_delivery(state_session):
    repo = FulltextReconcileStateRepository(state_session)
    now = datetime(2026, 9, 17, 1)
    first = await repo.request_repair(12, "fingerprint", "parse", now)
    second = await repo.request_repair(12, "fingerprint", "parse", now)
    assert first.task_id == second.task_id
    assert await repo.claim_repair(12, "fingerprint", first.task_id, now)
    assert not await repo.claim_repair(12, "fingerprint", first.task_id, now)
    await repo.finish_repair(12, "fingerprint", first.task_id, False, now)
    exhausted = await repo.request_repair(12, "fingerprint", "parse", now)
    assert exhausted.status == "exhausted"
    assert exhausted.attempts == 1


@pytest.mark.parametrize("final_status,minutes,expected", [
    ("ready", 10, "resolved"), ("failed", 10, "exhausted"), ("pending", 121, "exhausted"),
])
async def test_projection_handoff_waits_and_settles_without_republishing(state_session, final_status, minutes, expected):
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

    file = KnowledgeFile(id=12, knowledge_id=1, file_name="sample.txt", status=2, projection_status="pending", tenant_id=1)
    state_session.add(file)
    repo = FulltextReconcileStateRepository(state_session)
    now = datetime(2026, 9, 24, 1)
    ticket = await repo.request_repair(12, "fingerprint", "projection", now)
    assert await repo.claim_repair(12, "fingerprint", ticket.task_id, now)
    await repo.finish_repair(12, "fingerprint", ticket.task_id, None, now)
    await state_session.refresh(ticket)
    assert ticket.status == "waiting_projection"
    assert await repo.pending_repairs(now + timedelta(minutes=5)) == []
    file.projection_status = final_status
    state_session.add(file)
    await state_session.flush()
    assert await repo.pending_repairs(now + timedelta(minutes=minutes)) == []
    await state_session.refresh(ticket)
    assert ticket.status == expected
    assert ticket.attempts == 1


async def test_complete_round_scans_both_directions_and_retries_only_failed_file(state_session):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from test.knowledge.fulltext.test_fulltext_reconcile_service import Harness, snapshot

    now = datetime(2026, 9, 17, 1)
    h = Harness({1: ValueError("bad metadata"), 2: snapshot(2)})
    h.documents[9] = {"file_id": 9}
    h.repo.state = FulltextReconcileStateRepository(state_session)
    h.repo.source.upper_bound = AsyncMock(return_value=2)
    h.repo.source.page_ids = AsyncMock(
        side_effect=lambda after, upper, limit: [i for i in (1, 2) if after < i <= upper][:limit]
    )
    h.es.reverse_page = AsyncMock(side_effect=lambda after, limit: sorted(i for i in h.documents if i > after)[:limit])
    h.service.now = lambda: now
    h.service.batch_size = 1

    @asynccontextmanager
    async def factory():
        try:
            yield h.repo
            await state_session.commit()
        except BaseException:
            await state_session.rollback()
            raise

    h.service.repository_factory = factory
    result = await h.service.run()
    assert result["status"] == "waiting"
    assert 9 not in h.documents
    assert 2 in h.documents
    assert (await state_session.get(FulltextReconcileRun, result["run_id"])).phase == "retry"
    h.snapshots[1] = snapshot(1)
    now += timedelta(minutes=15)
    h.repo.source.snapshots.reset_mock()
    retried = await h.service.run(create=False)
    assert retried["run_id"] == result["run_id"]
    assert retried["status"] == "completed"
    h.repo.source.snapshots.assert_awaited_once_with([1])


async def test_waiting_round_expires_and_new_day_can_start(state_session):
    repo = FulltextReconcileStateRepository(state_session)
    now = datetime(2026, 9, 17, 1)
    run = await repo.load_or_create(now, 100)
    await repo.checkpoint(run.id, "forward", 100, {2: "waiting_source"}, {}, now)
    await repo.transition(run.id, "retry", now)
    assert await repo.finish_scan(run.id, now) == "waiting"
    assert await repo.finish_scan(run.id, now + timedelta(days=1)) == "completed_with_errors"
    following = await repo.load_or_create(now + timedelta(days=1), 101)
    assert following.id != run.id
    assert following.upper_id == 101


async def test_reverse_existence_check_does_not_resolve_forward_content_failure(state_session):
    repo = FulltextReconcileStateRepository(state_session)
    now = datetime(2026, 9, 17, 1)
    run = await repo.load_or_create(now, 100)
    await repo.checkpoint(run.id, "forward", 100, {2: "compare:ReconcileReadError"}, {}, now)
    await repo.checkpoint(run.id, "reverse", 100, {}, {2: "reverse_existing"}, now)
    issue = await state_session.get(FulltextReconcileIssue, (run.id, 2))
    assert issue.status == "pending"
