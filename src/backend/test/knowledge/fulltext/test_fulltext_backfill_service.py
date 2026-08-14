from datetime import datetime
from unittest.mock import AsyncMock

from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import KnowledgeFulltextOutbox
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import KnowledgeFulltextFileSnapshot
from bisheng.knowledge.domain.services.knowledge_fulltext_backfill_service import (
    KnowledgeFulltextBackfillCandidate,
    KnowledgeFulltextBackfillService,
    KnowledgeFulltextBackfillTarget,
)


def snapshot(**updates) -> KnowledgeFulltextFileSnapshot:
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


def outbox(**updates) -> KnowledgeFulltextOutbox:
    values = {
        "id": 101,
        "tenant_id": 1,
        "aggregate_type": "file",
        "aggregate_id": 7,
        "knowledge_id": 9,
        "desired_action": "sync_current",
        "desired_revision": 3,
        "applied_revision": 1,
        "trigger_type": "historical_backfill",
        "status": "pending",
        "retry_count": 0,
        "max_retries": 8,
    }
    values.update(updates)
    return KnowledgeFulltextOutbox(**values)


def service():
    source_repository = AsyncMock()
    outbox_repository = AsyncMock()
    result = KnowledgeFulltextBackfillService(
        source_repository=source_repository,
        outbox_repository=outbox_repository,
        max_retries=8,
    )
    return result, source_repository, outbox_repository


async def test_inspect_page_reuses_current_eligibility_and_never_writes():
    backfill, source_repository, outbox_repository = service()
    source_repository.list_backfill_file_ids.return_value = [7, 8, 9, 10]
    source_repository.get_current_snapshot.side_effect = [
        snapshot(file_id=7),
        snapshot(file_id=8, status="1"),
        snapshot(file_id=9, status="3"),
        None,
    ]

    page = await backfill.inspect_page(
        after_file_id=3,
        limit=20,
        knowledge_id=9,
        file_id=None,
    )

    source_repository.list_backfill_file_ids.assert_awaited_once_with(
        after_file_id=3,
        limit=20,
        knowledge_id=9,
        file_id=None,
    )
    assert page.scanned_count == 4
    assert page.next_start_after_id == 10
    assert page.candidates == (KnowledgeFulltextBackfillCandidate(file_id=7, knowledge_id=9),)
    assert page.excluded_counts == {"keep": 1, "delete": 1, "missing": 1}
    outbox_repository.request_sync.assert_not_awaited()


async def test_request_target_creates_file_sync_and_repeated_run_increases_revision():
    backfill, _source_repository, outbox_repository = service()
    outbox_repository.request_sync.side_effect = [outbox(desired_revision=3), outbox(desired_revision=4)]
    candidate = KnowledgeFulltextBackfillCandidate(file_id=7, knowledge_id=9)

    first = await backfill.request_target(candidate)
    second = await backfill.request_target(candidate)

    assert first == KnowledgeFulltextBackfillTarget(file_id=7, outbox_id=101, target_revision=3)
    assert second.target_revision == 4
    assert outbox_repository.request_sync.await_count == 2
    call = outbox_repository.request_sync.await_args
    assert call.kwargs["aggregate_type"].value == "file"
    assert call.kwargs["desired_action"].value == "sync_current"
    assert call.kwargs["trigger_type"] == "historical_backfill"


async def test_target_status_uses_revision_threshold_and_distinguishes_terminal_failure():
    backfill, _source_repository, outbox_repository = service()
    targets = [
        KnowledgeFulltextBackfillTarget(file_id=7, outbox_id=101, target_revision=3),
        KnowledgeFulltextBackfillTarget(file_id=8, outbox_id=102, target_revision=5),
        KnowledgeFulltextBackfillTarget(file_id=9, outbox_id=103, target_revision=2),
        KnowledgeFulltextBackfillTarget(file_id=10, outbox_id=104, target_revision=2),
    ]
    outbox_repository.list_by_ids.return_value = [
        outbox(id=101, aggregate_id=7, desired_revision=4, applied_revision=4, status="pending"),
        outbox(
            id=102,
            aggregate_id=8,
            desired_revision=5,
            applied_revision=3,
            status="failed",
            retry_count=8,
            max_retries=8,
        ),
        outbox(id=103, aggregate_id=9, desired_revision=2, applied_revision=1, status="processing"),
        outbox(id=104, aggregate_id=10, desired_revision=2, applied_revision=1, status="pending"),
    ]

    statuses = await backfill.classify_targets(targets)

    assert statuses == {"success": 1, "failed": 1, "processing": 1, "pending": 1}
    outbox_repository.list_by_ids.assert_awaited_once_with([101, 102, 103, 104])

