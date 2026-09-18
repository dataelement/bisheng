"""Lease, generation and failure-isolation tests for F059 projections."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_document_projection_service import (
    KnowledgeDocumentProjectionError,
    KnowledgeDocumentProjectionService,
)


async def _seed_entries(session: AsyncSession) -> None:
    session.add_all(
        [
            KnowledgeFile(
                id=100,
                tenant_id=7,
                knowledge_id=20,
                file_name="manager.pdf",
                object_name="tenant/7/manager.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                desired_content_generation=4,
                applied_content_generation=4,
                desired_entry_generation=1,
                applied_entry_generation=1,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
            ),
            KnowledgeFile(
                id=101,
                tenant_id=7,
                knowledge_id=10,
                file_name="manager.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.PUBLISH.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_previous_file_id=100,
                desired_content_generation=4,
                applied_content_generation=0,
                desired_entry_generation=1,
                applied_entry_generation=0,
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
            ),
            KnowledgeFile(
                id=102,
                tenant_id=7,
                knowledge_id=30,
                file_name="manager.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.SHARE.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                desired_content_generation=4,
                applied_content_generation=0,
                desired_entry_generation=1,
                applied_entry_generation=0,
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
            ),
        ]
    )
    await session.commit()


def _service(
    session: AsyncSession,
    *,
    writer=AsyncMock(),
    cleaner=AsyncMock(),
    finalizer=AsyncMock(),
) -> KnowledgeDocumentProjectionService:
    service = KnowledgeDocumentProjectionService(
        session=session,
        file_repository=KnowledgeFileRepositoryImpl(session),
        shared_storage_writer=AsyncMock(),
        deleting_entry_finalizer=finalizer,
        lease_seconds=30,
        max_retry_seconds=60,
    )
    # 此处只验证租约/CAS状态机；共享物理写入在 shared_space_projection 中验证。
    async def project(entry, target, **kwargs):
        await writer(entry, target)
    async def cleanup(entry, target):
        await cleaner(int(entry.knowledge_id), [int(entry.id)])
    service._process_shared_projection = project
    service._process_shared_cleanup = cleanup
    return service


@pytest.mark.asyncio
async def test_projection_claims_short_lease_and_applies_both_generations(
    async_db_session: AsyncSession,
):
    await _seed_entries(async_db_session)
    writer = AsyncMock()
    cleaner = AsyncMock()
    service = _service(
        async_db_session,
        writer=writer,
        cleaner=cleaner,
    )

    result = await service.process_entry(
        tenant_id=7,
        entry_id=101,
        lease_owner="worker-a",
        now=datetime(2026, 7, 27, 10, 0, 0),
    )

    entry = await KnowledgeFileRepositoryImpl(
        async_db_session
    ).find_by_id(101)
    assert writer.await_args.args[0].id == 101
    assert result.status == "ready"
    assert entry.applied_content_generation == 4
    assert entry.applied_entry_generation == 1
    assert entry.projection_status == KnowledgeFileProjectionStatus.READY.value
    assert entry.projection_lease_owner is None
    assert entry.projection_previous_file_id is None
    cleaner.assert_not_awaited()


@pytest.mark.asyncio
async def test_projection_rebuild_reopens_ready_share_without_changing_file_state(
    async_db_session: AsyncSession,
):
    await _seed_entries(async_db_session)
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    entry = await repository.find_by_id(102)
    entry.applied_content_generation = entry.desired_content_generation
    entry.applied_entry_generation = entry.desired_entry_generation
    entry.projection_status = KnowledgeFileProjectionStatus.READY.value
    async_db_session.add(entry)
    await async_db_session.commit()

    assert await repository.request_projection_rebuild(102)

    pending = await repository.find_by_id(102)
    assert pending.projection_status == KnowledgeFileProjectionStatus.PENDING.value

    writer = AsyncMock()
    result = await _service(async_db_session, writer=writer).process_entry(
        tenant_id=7,
        entry_id=102,
        lease_owner="fulltext-repair",
    )

    refreshed = await repository.find_by_id(102)
    assert result.status == "ready"
    assert writer.await_args.args[0].id == 102
    assert refreshed.status == KnowledgeFileStatus.SUCCESS.value
    assert refreshed.object_name is None
    assert refreshed.projection_status == KnowledgeFileProjectionStatus.READY.value


@pytest.mark.asyncio
async def test_projection_rebuild_reopens_failed_manager_and_resets_retry_state(
    async_db_session: AsyncSession,
):
    await _seed_entries(async_db_session)
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    manager.projection_status = KnowledgeFileProjectionStatus.FAILED.value
    manager.projection_retry_count = 99
    manager.projection_last_error = "retry_exhausted:missing chunks"
    async_db_session.add(manager)
    await async_db_session.commit()

    assert await repository.request_projection_rebuild(100)
    reopened = await repository.find_by_id(100)
    assert reopened.projection_status == KnowledgeFileProjectionStatus.PENDING.value
    assert reopened.projection_retry_count == 0
    assert reopened.projection_last_error is None




@pytest.mark.asyncio
async def test_rollback_cleanup_waits_for_destination_manager_projection(
    async_db_session: AsyncSession,
):
    await _seed_entries(async_db_session)
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    manager.projection_status = KnowledgeFileProjectionStatus.PENDING.value
    manager.applied_content_generation = 3
    publish = await repository.find_by_id(101)
    publish.entry_status = KnowledgeFileEntryStatus.DELETING.value
    publish.projection_status = KnowledgeFileProjectionStatus.PENDING.value
    async_db_session.add_all([manager, publish])
    await async_db_session.commit()
    cleaner = AsyncMock()

    result = await _service(async_db_session, cleaner=cleaner).process_entry(
        tenant_id=7, entry_id=101, lease_owner="worker-cleanup",
    )
    assert result.status == "waiting_dependency"
    waiting = await repository.find_by_id(101)
    assert waiting.projection_retry_count == 0
    assert waiting.projection_next_retry_at > datetime.now()

    cleaner.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_generation_cannot_hide_newer_work(
    async_db_session: AsyncSession,
):
    await _seed_entries(async_db_session)
    repository = KnowledgeFileRepositoryImpl(async_db_session)

    async def write_and_advance(*_args):
        entry = await repository.find_by_id(101)
        entry.desired_content_generation = 5
        entry.projection_status = KnowledgeFileProjectionStatus.PENDING.value
        async_db_session.add(entry)
        await async_db_session.commit()

    service = _service(
        async_db_session,
        writer=AsyncMock(side_effect=write_and_advance),
    )
    result = await service.process_entry(
        tenant_id=7,
        entry_id=101,
        lease_owner="worker-old",
        now=datetime(2026, 7, 27, 10, 0, 0),
    )

    entry = await repository.find_by_id(101)
    assert result.status == "ready"
    assert entry.applied_content_generation == 4
    assert entry.desired_content_generation == 5
    assert entry.projection_status == (
        KnowledgeFileProjectionStatus.PENDING.value
    )


@pytest.mark.asyncio
async def test_projection_failure_preserves_applied_generation_and_backs_off(
    async_db_session: AsyncSession,
):
    await _seed_entries(async_db_session)
    now = datetime(2026, 7, 27, 10, 0, 0)
    service = _service(
        async_db_session,
        writer=AsyncMock(side_effect=RuntimeError("ES unavailable")),
    )

    with pytest.raises(RuntimeError, match="ES unavailable"):
        await service.process_entry(
            tenant_id=7,
            entry_id=101,
            lease_owner="worker-a",
            now=now,
        )

    entry = await KnowledgeFileRepositoryImpl(
        async_db_session
    ).find_by_id(101)
    assert entry.applied_content_generation == 0
    assert entry.projection_status == (
        KnowledgeFileProjectionStatus.FAILED.value
    )
    assert entry.projection_retry_count == 1
    assert entry.projection_next_retry_at > now
    assert entry.projection_lease_owner is None
    assert entry.projection_last_error == "RuntimeError:ES unavailable"


@pytest.mark.asyncio
async def test_old_worker_failure_cannot_clear_new_projection_lease(
    async_db_session: AsyncSession,
):
    await _seed_entries(async_db_session)
    repository = KnowledgeFileRepositoryImpl(async_db_session)

    async def lose_lease_then_fail(*_args):
        entry = await repository.find_by_id(101)
        entry.projection_lease_owner = "worker-new"
        entry.projection_lease_until = datetime.now() + timedelta(seconds=30)
        entry.projection_status = (
            KnowledgeFileProjectionStatus.PROCESSING.value
        )
        async_db_session.add(entry)
        await async_db_session.commit()
        raise RuntimeError("old worker failed")

    with pytest.raises(RuntimeError, match="old worker failed"):
        await _service(
            async_db_session,
            writer=AsyncMock(side_effect=lose_lease_then_fail),
        ).process_entry(
            tenant_id=7,
            entry_id=101,
            lease_owner="worker-old",
        )

    entry = await repository.find_by_id(101)
    assert entry.projection_lease_owner == "worker-new"
    assert entry.projection_status == (
        KnowledgeFileProjectionStatus.PROCESSING.value
    )
    assert entry.projection_retry_count == 0


@pytest.mark.asyncio
async def test_deleting_entry_cleans_projection_before_finalizer(
    async_db_session: AsyncSession,
):
    await _seed_entries(async_db_session)
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    entry = await repository.find_by_id(102)
    entry.entry_status = KnowledgeFileEntryStatus.DELETING.value
    entry.projection_status = KnowledgeFileProjectionStatus.PENDING.value
    async_db_session.add(entry)
    await async_db_session.commit()
    events: list[str] = []

    async def clean(_space_id, _file_ids):
        events.append("clean")

    async def finalize(_entry):
        events.append("finalize")

    result = await _service(
        async_db_session,
        cleaner=AsyncMock(side_effect=clean),
        finalizer=AsyncMock(side_effect=finalize),
    ).process_entry(
        tenant_id=7,
        entry_id=102,
        lease_owner="worker-a",
    )

    assert result.status == "cleaned"
    assert events == ["clean", "finalize"]


@pytest.mark.asyncio
async def test_expired_processing_lease_is_returned_by_due_scan(
    async_db_session: AsyncSession,
):
    await _seed_entries(async_db_session)
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    entry = await repository.find_by_id(101)
    entry.projection_status = KnowledgeFileProjectionStatus.PROCESSING.value
    entry.projection_lease_owner = "dead-worker"
    entry.projection_lease_until = datetime.now() - timedelta(seconds=1)
    async_db_session.add(entry)
    await async_db_session.commit()

    due = await _service(async_db_session).list_due_entry_ids(
        now=datetime.now(),
        limit=10,
    )

    assert 101 in due


@pytest.mark.asyncio
async def test_projection_retry_cap_removes_exhausted_entry_from_due_scan(
    async_db_session: AsyncSession,
):
    await _seed_entries(async_db_session)
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    entry = await repository.find_by_id(101)
    entry.projection_status = KnowledgeFileProjectionStatus.FAILED.value
    entry.projection_retry_count = 3
    entry.projection_next_retry_at = datetime.now() - timedelta(seconds=1)
    async_db_session.add(entry)
    await async_db_session.commit()

    service = KnowledgeDocumentProjectionService(
        session=async_db_session,
        file_repository=repository,
        max_retry_attempts=3,
    )
    due = await service.list_due_entry_ids(now=datetime.now(), limit=10)

    assert 101 not in due


@pytest.mark.asyncio
async def test_dependency_wait_survives_retry_budget_and_resumes(async_db_session):
    await _seed_entries(async_db_session)
    repo = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repo.find_by_id(100)
    manager.projection_status = "failed"
    manager.projection_retry_count = 8
    entry = await repo.find_by_id(101)
    entry.entry_type = "projection_tombstone"
    entry.entry_status = "deleting"
    await async_db_session.commit()
    cleaner, finalizer = AsyncMock(), AsyncMock()
    service = _service(async_db_session, cleaner=cleaner, finalizer=finalizer)
    service.max_retry_attempts = 2
    now = datetime.now()
    for attempt in range(4):
        result = await service.process_entry(
            tenant_id=7, entry_id=101, lease_owner=f"wait-{attempt}", now=now,
        )
        assert result.status == "waiting_dependency"
        waiting = await repo.find_by_id(101)
        assert waiting.projection_retry_count == 0
        assert waiting.projection_lease_owner is None
        assert waiting.projection_next_retry_at > now
        now = waiting.projection_next_retry_at + timedelta(seconds=1)
    cleaner.assert_not_awaited()
    finalizer.assert_not_awaited()
    manager = await repo.find_by_id(100)
    manager.projection_status = "ready"
    await async_db_session.commit()
    result = await service.process_entry(
        tenant_id=7, entry_id=101, lease_owner="resumed", now=now,
    )
    assert result.status == "cleaned"
    finalizer.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalizer_failure_is_persisted_and_retry_is_bounded(async_db_session):
    await _seed_entries(async_db_session)
    repo = KnowledgeFileRepositoryImpl(async_db_session)
    entry = await repo.find_by_id(101)
    entry.entry_type = "projection_tombstone"
    entry.entry_status = "deleting"
    await async_db_session.commit()
    service = _service(async_db_session, finalizer=AsyncMock(side_effect=RuntimeError("FGA unavailable")))
    service.max_retry_attempts = 2
    now = datetime.now()
    for attempt in range(2):
        with pytest.raises(RuntimeError, match="FGA unavailable"):
            await service.process_entry(tenant_id=7, entry_id=101, lease_owner=f"failure-{attempt}", now=now)
        failed = await repo.find_by_id(101)
        assert failed.projection_status == "failed"
        assert failed.projection_retry_count == attempt + 1
        assert "FGA unavailable" in failed.projection_last_error
        assert failed.projection_next_retry_at > now
        assert failed.projection_lease_owner is None
        now = failed.projection_next_retry_at + timedelta(seconds=1)
    assert 101 not in await service.list_due_entry_ids(now=now)


@pytest.mark.asyncio
async def test_cleanup_generation_change_does_not_finalize_newer_work(async_db_session):
    await _seed_entries(async_db_session)
    repo = KnowledgeFileRepositoryImpl(async_db_session)
    entry = await repo.find_by_id(101)
    entry.entry_status = "deleting"
    await async_db_session.commit()

    async def advance(*args):
        current = await repo.find_by_id(101)
        current.desired_entry_generation += 1
        await async_db_session.commit()

    finalizer = AsyncMock()
    result = await _service(async_db_session, cleaner=AsyncMock(side_effect=advance), finalizer=finalizer).process_entry(
        tenant_id=7, entry_id=101, lease_owner="old-cleanup",
    )
    assert result.status == "stale"
    finalizer.assert_not_awaited()


@pytest.mark.asyncio
async def test_aged_reconcile_cursor_reaches_entries_after_first_page(async_db_session):
    old = datetime.now() - timedelta(hours=1)
    for i in range(101):
        async_db_session.add(KnowledgeFile(
            id=1000+i, tenant_id=7, knowledge_id=3637, file_name="cleanup.doc",
            reference_document_id=1000+i, entry_type="projection_tombstone",
            entry_status="deleting" if i < 100 else "preparing",
            projection_status="failed", projection_retry_count=8, update_time=old,
        ))
    await async_db_session.commit()
    repo = KnowledgeFileRepositoryImpl(async_db_session)
    first = await repo.find_permission_reconcile_candidates(older_than=old, limit=100)
    second = await repo.find_permission_reconcile_candidates(older_than=old, limit=100, after_id=first[-1].id)
    assert [row.id for row in second] == [1100]


@pytest.mark.asyncio
async def test_crash_after_projection_commit_can_resume_after_lease_expiry(async_db_session):
    import asyncio

    await _seed_entries(async_db_session)
    repo = KnowledgeFileRepositoryImpl(async_db_session)
    row = await repo.find_by_id(101)
    row.entry_status = "deleting"
    await async_db_session.commit()
    finalizer = AsyncMock(side_effect=asyncio.CancelledError())
    service = _service(async_db_session, finalizer=finalizer)
    now = datetime.now()
    with pytest.raises(asyncio.CancelledError):
        await service.process_entry(tenant_id=7, entry_id=101, lease_owner="crashed", now=now)
    row = await repo.find_by_id(101)
    assert row.projection_lease_owner == "crashed"
    assert row.projection_status == "ready"
    assert (await service.process_entry(tenant_id=7, entry_id=101, lease_owner="too-early", now=now)).status == "not_claimed"
    finalizer.side_effect = None
    result = await service.process_entry(tenant_id=7, entry_id=101, lease_owner="resumed", now=now + timedelta(seconds=31))
    assert result.status == "cleaned"


@pytest.mark.asyncio
async def test_missing_canonical_document_consumes_bounded_retry(async_db_session):
    await _seed_entries(async_db_session)
    service = _service(async_db_session)
    service.document_repository = AsyncMock()
    service.document_repository.find_by_id.return_value = None
    service.version_repository = AsyncMock()
    with pytest.raises(KnowledgeDocumentProjectionError, match="canonical document is unavailable"):
        await service.process_entry(tenant_id=7, entry_id=101, lease_owner="missing-canonical")
    row = await service.file_repository.find_by_id(101)
    assert row.projection_status == "failed"
    assert row.projection_retry_count == 1
