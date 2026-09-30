"""Repository contracts for F059 distribution locking and projection recovery."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)


def _file(file_id: int, **overrides) -> KnowledgeFile:
    values = {
        "id": file_id,
        "tenant_id": 1,
        "knowledge_id": 12,
        "file_name": f"{file_id}.pdf",
    }
    values.update(overrides)
    return KnowledgeFile(**values)


async def test_projection_checks_batch_ready_entries_without_resetting_failures_or_leases(async_db_session):
    now = datetime.now()
    base = {"reference_document_id": 91, "entry_type": "manager", "entry_status": "active", "projection_status": "ready"}
    rows = [_file(i, **base) for i in range(1, 502)]
    failed = _file(502, **{**base, "projection_status": "failed"}, projection_retry_count=4,
                   projection_last_error="retry_exhausted", projection_next_retry_at=now)
    rebuilding = _file(503, **{**base, "projection_status": "pending"}, projection_retry_count=2,
                       projection_lease_owner="rebuild:owner", projection_lease_until=now + timedelta(minutes=3))
    deleted = _file(504, **base, deleted_at=now)
    deleting = _file(505, **{**base, "entry_status": "deleting"})
    legacy = _file(506, projection_status="ready")
    async_db_session.add_all([*rows, failed, rebuilding, deleted, deleting, legacy])
    await async_db_session.commit()
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    assert await repository.request_projection_checks(list(range(1, 507))) == 501
    await async_db_session.commit()
    for row in [*rows, failed, rebuilding, deleted, deleting, legacy]:
        await async_db_session.refresh(row)
    assert all(row.projection_status == "pending" for row in rows)
    assert (failed.projection_status, failed.projection_retry_count, failed.projection_last_error) == (
        "failed", 4, "retry_exhausted",
    )
    assert (rebuilding.projection_lease_owner, rebuilding.projection_retry_count) == ("rebuild:owner", 2)
    assert deleted.projection_status == deleting.projection_status == "ready"
    assert legacy.projection_status != "pending"
    assert await repository.request_projection_checks(list(range(1, 507))) == 0


@pytest.mark.asyncio
async def test_distribution_row_locks_return_stable_id_order(
    async_db_session: AsyncSession,
):
    async_db_session.add_all(
        [
            KnowledgeDocument(id=3, tenant_id=1, knowledge_id=12),
            KnowledgeDocument(id=1, tenant_id=1, knowledge_id=12),
            KnowledgeDocument(id=2, tenant_id=1, knowledge_id=12),
            _file(3),
            _file(1),
            _file(2),
        ]
    )
    await async_db_session.commit()

    document_repository = KnowledgeDocumentRepositoryImpl(async_db_session)
    file_repository = KnowledgeFileRepositoryImpl(async_db_session)

    documents = await document_repository.find_by_ids_for_update([3, 1, 2])
    files = await file_repository.find_by_ids_for_update([3, 1, 2])

    assert [document.id for document in documents] == [1, 2, 3]
    assert [knowledge_file.id for knowledge_file in files] == [1, 2, 3]


@pytest.mark.asyncio
async def test_projection_candidate_scan_uses_complete_retry_predicate(
    async_db_session: AsyncSession,
):
    now = datetime(2026, 7, 27, 12, 0, 0)
    future = now + timedelta(minutes=5)

    async_db_session.add_all(
        [
            _file(
                1,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
                desired_content_generation=2,
                applied_content_generation=1,
            ),
            _file(
                2,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.PUBLISH.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
                desired_entry_generation=2,
                applied_entry_generation=1,
            ),
            _file(
                3,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.SHARE.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
            ),
            _file(
                4,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.SHARE.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_status=KnowledgeFileProjectionStatus.FAILED.value,
                projection_next_retry_at=future,
            ),
            _file(
                5,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.SHARE.value,
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
                projection_lease_until=future,
            ),
            _file(
                6,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.SHARE.value,
                entry_status=KnowledgeFileEntryStatus.DELETING.value,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
            ),
            _file(
                7,
                entry_type=KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
                entry_status=KnowledgeFileEntryStatus.DELETING.value,
                projection_status=KnowledgeFileProjectionStatus.READY.value,
            ),
            _file(
                8,
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
            ),
            _file(
                9,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.SHARE.value,
                entry_status=KnowledgeFileEntryStatus.PREPARING.value,
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
            ),
            _file(
                10,
                entry_type=(
                    KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value
                ),
                entry_status=KnowledgeFileEntryStatus.PREPARING.value,
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
            ),
        ]
    )
    await async_db_session.commit()

    repository = KnowledgeFileRepositoryImpl(async_db_session)
    candidates = await repository.find_projection_candidates(now=now, limit=20)

    assert [entry.id for entry in candidates] == [1, 2, 3, 6, 7]


@pytest.mark.asyncio
async def test_projection_lease_and_apply_are_token_and_generation_cas(
    async_db_session: AsyncSession,
):
    now = datetime(2026, 7, 27, 12, 0, 0)
    entry = _file(
        1,
        reference_document_id=91,
        entry_type=KnowledgeFileEntryType.MANAGER.value,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
        desired_content_generation=2,
        desired_entry_generation=3,
    )
    async_db_session.add(entry)
    await async_db_session.commit()

    repository = KnowledgeFileRepositoryImpl(async_db_session)
    claimed = await repository.claim_projection_lease(
        entry_id=1,
        lease_owner="worker-a",
        lease_until=now + timedelta(minutes=1),
        now=now,
    )
    assert claimed is not None
    assert claimed.projection_lease_owner == "worker-a"
    assert claimed.projection_status == KnowledgeFileProjectionStatus.PROCESSING.value

    stale_applied = await repository.apply_projection_result(
        entry_id=1,
        lease_owner="worker-b",
        target_content_generation=2,
        target_entry_generation=3,
    )
    assert stale_applied is False

    applied = await repository.apply_projection_result(
        entry_id=1,
        lease_owner="worker-a",
        target_content_generation=2,
        target_entry_generation=3,
    )
    assert applied is True

    refreshed = await repository.find_by_id(1)
    assert refreshed.applied_content_generation == 2
    assert refreshed.applied_entry_generation == 3
    assert refreshed.projection_status == KnowledgeFileProjectionStatus.READY.value
    assert refreshed.projection_lease_owner is None


@pytest.mark.asyncio
async def test_document_pointer_update_flushes_without_committing():
    result = SimpleNamespace(rowcount=1)
    session = SimpleNamespace(
        execute=AsyncMock(return_value=result),
        flush=AsyncMock(),
        commit=AsyncMock(),
    )
    repository = KnowledgeDocumentRepositoryImpl(session)

    await repository.update_primary_version_id(91, 501)

    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()
