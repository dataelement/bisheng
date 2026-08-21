from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import KnowledgeFulltextOutbox
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextEngagementCounts,
    KnowledgeFulltextFileSnapshot,
    KnowledgeFulltextRebuiltContent,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_document_service import (
    KnowledgeFulltextDocumentService,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_rebuild_service import (
    KnowledgeFulltextProjectionNotReadyError,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_sync_service import (
    KnowledgeFulltextSyncService,
)


def outbox(**updates):
    values = {
        "id": 1,
        "tenant_id": 1,
        "aggregate_type": "file",
        "aggregate_id": 7,
        "knowledge_id": 9,
        "desired_action": "sync_current",
        "desired_revision": 2,
        "applied_revision": 1,
        "trigger_type": "test",
        "status": "processing",
        "lease_owner": "worker-a",
    }
    values.update(updates)
    return KnowledgeFulltextOutbox(**values)


def snapshot(**updates):
    values = {
        "file_id": 7,
        "knowledge_id": 9,
        "file_type": "FILE",
        "status": "2",
        "file_name": "制度.pdf",
        "file_source": "upload",
        "knowledge_name": "制度库",
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 2),
    }
    values.update(updates)
    return KnowledgeFulltextFileSnapshot(**values)


def service():
    outbox_repository = AsyncMock()
    source_repository = AsyncMock()
    chunk_repository = AsyncMock()
    index_repository = AsyncMock()
    rebuild_service = MagicMock()
    rebuild_service.rebuild.return_value = KnowledgeFulltextRebuiltContent(
        content="正文", chunk_count=1, content_hash="abc"
    )
    sync_service = KnowledgeFulltextSyncService(
        outbox_repository=outbox_repository,
        source_repository=source_repository,
        chunk_repository=chunk_repository,
        index_repository=index_repository,
        rebuild_service=rebuild_service,
        document_service=KnowledgeFulltextDocumentService(index_schema_version=1),
        fanout_batch_size=2,
    )
    return sync_service, outbox_repository, source_repository, chunk_repository, index_repository


async def test_file_sync_upserts_current_document_after_revision_preflight():
    sync, outbox_repo, source_repo, chunk_repo, index_repo = service()
    source_repo.get_current_snapshot.return_value = snapshot()
    source_repo.get_knowledge_index_name.return_value = "knowledge_9"
    outbox_repo.is_current_lease.return_value = True
    outbox_repo.mark_success.return_value = True

    result = await sync.sync_claimed(outbox(), lease_owner="worker-a", now=datetime(2026, 1, 3))

    assert result == "upsert"
    chunk_repo.list_all.assert_awaited_once_with(index_name="knowledge_9", file_id=7, knowledge_id=9)
    index_repo.upsert.assert_awaited_once()
    assert index_repo.upsert.await_args.args[0].sync_revision == 2
    outbox_repo.mark_success.assert_awaited_once()


async def test_first_document_upsert_seeds_current_engagement_counts():
    sync, outbox_repo, source_repo, _chunk_repo, index_repo = service()
    engagement_repository = AsyncMock()
    engagement_repository.get_totals.return_value = {
        7: KnowledgeFulltextEngagementCounts(file_id=7, preview_count=9, download_count=4)
    }
    sync.engagement_repository = engagement_repository
    source_repo.get_current_snapshot.return_value = snapshot()
    source_repo.get_knowledge_index_name.return_value = "knowledge_9"
    outbox_repo.is_current_lease.return_value = True

    await sync.sync_claimed(outbox(), lease_owner="worker-a", now=datetime(2026, 1, 3))

    document = index_repo.upsert.await_args.args[0]
    assert document.preview_count == 9
    assert document.download_count == 4


@pytest.mark.parametrize(
    ("current_snapshot", "expected"),
    [
        (None, "delete"),
        (snapshot(status="3"), "delete"),
        (snapshot(status="1"), "keep"),
    ],
)
async def test_file_sync_converges_delete_and_keep_without_partial_build(current_snapshot, expected):
    sync, outbox_repo, source_repo, chunk_repo, index_repo = service()
    source_repo.get_current_snapshot.return_value = current_snapshot
    outbox_repo.is_current_lease.return_value = True
    outbox_repo.mark_success.return_value = True

    result = await sync.sync_claimed(outbox(), lease_owner="worker-a", now=datetime(2026, 1, 3))

    assert result == expected
    if expected == "delete":
        index_repo.delete.assert_awaited_once_with(7)
    else:
        index_repo.delete.assert_not_awaited()
    index_repo.upsert.assert_not_awaited()
    chunk_repo.list_all.assert_not_awaited()


async def test_file_sync_keeps_current_index_when_projection_is_not_ready():
    sync, outbox_repo, source_repo, chunk_repo, index_repo = service()
    source_repo.get_current_snapshot.return_value = snapshot(
        logical_document_id=10,
        entry_type="publish",
        entry_status="active",
        projection_status="pending",
    )
    outbox_repo.is_current_lease.return_value = True

    result = await sync.sync_claimed(outbox(), lease_owner="worker-a", now=datetime(2026, 1, 3))

    assert result == "keep"
    source_repo.get_knowledge_index_name.assert_not_awaited()
    chunk_repo.list_all.assert_not_awaited()
    index_repo.upsert.assert_not_awaited()
    index_repo.delete.assert_not_awaited()
    outbox_repo.mark_success.assert_awaited_once()


async def test_file_sync_retries_when_knowledge_rag_index_is_not_ready():
    sync, _outbox_repo, source_repo, *_ = service()
    source_repo.get_current_snapshot.return_value = snapshot(
        logical_document_id=10,
        entry_type="publish",
        entry_status="active",
        projection_status="ready",
    )
    source_repo.get_knowledge_index_name.return_value = None

    with pytest.raises(KnowledgeFulltextProjectionNotReadyError, match="knowledge RAG index is not ready"):
        await sync.sync_claimed(outbox(), lease_owner="worker-a", now=datetime(2026, 1, 3))


async def test_stale_revision_never_writes_index():
    sync, outbox_repo, source_repo, _chunk_repo, index_repo = service()
    source_repo.get_current_snapshot.return_value = snapshot()
    source_repo.get_knowledge_index_name.return_value = "knowledge_9"
    outbox_repo.is_current_lease.return_value = False

    result = await sync.sync_claimed(outbox(), lease_owner="worker-a", now=datetime(2026, 1, 3))

    assert result == "stale"
    index_repo.upsert.assert_not_awaited()
    index_repo.delete.assert_not_awaited()
    outbox_repo.release_pending.assert_awaited_once()


async def test_scope_fanout_pages_by_stable_file_id_and_scope_delete_is_direct():
    sync, outbox_repo, source_repo, _chunk_repo, index_repo = service()
    source_repo.list_file_ids.return_value = [11, 12]

    result = await sync.sync_claimed(
        outbox(
            aggregate_type="knowledge",
            aggregate_id=9,
            desired_action="fanout_current",
            fanout_cursor={"file_id": 10},
        ),
        lease_owner="worker-a",
        now=datetime(2026, 1, 3),
    )

    assert result == "fanout_pending"
    source_repo.list_file_ids.assert_awaited_once_with(knowledge_id=9, after_file_id=10, limit=2)
    assert outbox_repo.request_sync.await_count == 2
    outbox_repo.save_fanout_cursor.assert_awaited_once_with(
        outbox_id=1, revision=2, lease_owner="worker-a", cursor={"file_id": 12}
    )

    outbox_repo.mark_success.reset_mock()
    result = await sync.sync_claimed(
        outbox(aggregate_type="knowledge", aggregate_id=9, desired_action="delete_scope"),
        lease_owner="worker-a",
        now=datetime(2026, 1, 3),
    )
    assert result == "delete_scope"
    index_repo.delete_scope.assert_awaited_once_with(9)
    outbox_repo.mark_success.assert_awaited_once()
