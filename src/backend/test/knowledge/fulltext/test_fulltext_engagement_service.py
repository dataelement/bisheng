from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import KnowledgeFulltextEngagementCounts
from bisheng.knowledge.domain.services.knowledge_fulltext_engagement_service import (
    KnowledgeFulltextEngagementService,
)


@pytest.mark.parametrize(
    ("event_type", "source_app", "status", "file_id", "expected"),
    [
        ("portal_document_read", "shougang_portal", "success", 11, True),
        ("portal_document_download", "shougang_portal", "success", "12", True),
        ("portal_document_read", "other", "success", 11, False),
        ("portal_document_read", "shougang_portal", "failed", 11, False),
        ("portal_favorite", "shougang_portal", "success", 11, False),
        ("portal_document_download", "shougang_portal", "success", 0, False),
    ],
)
async def test_projection_scope_matrix(event_type, source_app, status, file_id, expected):
    statistics_repository = AsyncMock()
    queue_repository = AsyncMock()
    scheduler = Mock()
    service = KnowledgeFulltextEngagementService(
        statistics_repository=statistics_repository,
        queue_repository=queue_repository,
        index_repository=AsyncMock(),
        scheduler=scheduler,
    )

    result = await service.project_event(
        event_type=event_type,
        source_app=source_app,
        status=status,
        file_id=file_id,
        occurred_at=datetime(2026, 8, 13, 16, 30, tzinfo=timezone.utc),
    )

    assert result is expected
    if expected:
        statistics_repository.increment_daily.assert_awaited_once()
        assert statistics_repository.increment_daily.await_args.kwargs["local_date"] == "2026-08-14"
        queue_repository.enqueue.assert_awaited_once()
        scheduler.assert_called_once()
    else:
        statistics_repository.increment_daily.assert_not_awaited()
        queue_repository.enqueue.assert_not_awaited()
        scheduler.assert_not_called()


async def test_statistics_sync_uses_absolute_totals_and_never_reads_chunks():
    statistics_repository = AsyncMock()
    statistics_repository.get_totals.return_value = {
        11: KnowledgeFulltextEngagementCounts(file_id=11, preview_count=7, download_count=3),
        12: KnowledgeFulltextEngagementCounts(file_id=12),
    }
    index_repository = AsyncMock()
    queue_repository = AsyncMock()
    service = KnowledgeFulltextEngagementService(
        statistics_repository=statistics_repository,
        queue_repository=queue_repository,
        index_repository=index_repository,
        scheduler=Mock(),
    )

    await service.sync_file_ids(
        [11, 12],
        updated_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
    )

    statistics_repository.get_totals.assert_awaited_once_with([11, 12])
    index_repository.bulk_update_engagement.assert_awaited_once()
    assert not hasattr(service, "chunk_repository")
    assert not hasattr(service, "rebuild_service")
