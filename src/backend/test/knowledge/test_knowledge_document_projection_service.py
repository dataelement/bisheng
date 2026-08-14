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
    return KnowledgeDocumentProjectionService(
        session=session,
        file_repository=KnowledgeFileRepositoryImpl(session),
        projection_writer=writer,
        projection_cleaner=cleaner,
        deleting_entry_finalizer=finalizer,
        lease_seconds=30,
        max_retry_seconds=60,
    )


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
    source = writer.await_args.args[0]
    assert source.space_id == 10
    assert source.file_id == 100
    assert result.status == "ready"
    assert entry.applied_content_generation == 4
    assert entry.applied_entry_generation == 1
    assert entry.projection_status == KnowledgeFileProjectionStatus.READY.value
    assert entry.projection_lease_owner is None
    assert entry.projection_previous_file_id is None
    cleaner.assert_awaited_once_with(10, [100])


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
    assert not await repository.request_projection_rebuild(100)

    pending = await repository.find_by_id(102)
    assert pending.projection_status == KnowledgeFileProjectionStatus.PENDING.value

    writer = AsyncMock()
    result = await _service(async_db_session, writer=writer).process_entry(
        tenant_id=7,
        entry_id=102,
        lease_owner="fulltext-repair",
    )

    refreshed = await repository.find_by_id(102)
    source = writer.await_args.args[0]
    assert result.status == "ready"
    assert source.file_id == 100
    assert refreshed.status == KnowledgeFileStatus.SUCCESS.value
    assert refreshed.object_name is None
    assert refreshed.projection_status == KnowledgeFileProjectionStatus.READY.value


@pytest.mark.asyncio
async def test_cross_space_manager_uses_publish_source_anchor(
    async_db_session: AsyncSession,
):
    await _seed_entries(async_db_session)
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    manager = await repository.find_by_id(100)
    manager.projection_previous_file_id = 101
    manager.projection_status = KnowledgeFileProjectionStatus.PENDING.value
    async_db_session.add(manager)
    await async_db_session.commit()

    service = _service(async_db_session)
    source_before_publish_ready = await service._resolve_source(manager)
    assert source_before_publish_ready.space_id == 10
    assert source_before_publish_ready.file_id == 100

    publish = await repository.find_by_id(101)
    publish.applied_content_generation = 4
    publish.applied_entry_generation = 1
    publish.projection_status = KnowledgeFileProjectionStatus.READY.value
    async_db_session.add(publish)
    await async_db_session.commit()

    source_after_publish_ready = await service._resolve_source(manager)
    assert source_after_publish_ready.space_id == 10
    assert source_after_publish_ready.file_id == 101


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

    with pytest.raises(
        KnowledgeDocumentProjectionError,
        match="destination manager projection is not ready",
    ):
        await _service(
            async_db_session,
            cleaner=cleaner,
        ).process_entry(
            tenant_id=7,
            entry_id=101,
            lease_owner="worker-cleanup",
        )

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
    assert "ES unavailable" not in (entry.projection_last_error or "")


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
