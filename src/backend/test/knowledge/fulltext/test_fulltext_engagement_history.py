from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_engagement_repository_impl import (
    KnowledgeFulltextEngagementRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextEngagementBulkResult,
    KnowledgeFulltextEngagementCounts,
    KnowledgeFulltextEngagementDaily,
    KnowledgeFulltextEngagementHistoryPage,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_engagement_service import (
    KnowledgeFulltextEngagementService,
)


@pytest.mark.parametrize(
    ("event_type", "file_field", "metric"),
    [
        ("portal_document_read", "event_data.portal_document_read_file_id", "preview_count"),
        ("portal_document_download", "event_data.portal_document_download_file_id", "download_count"),
    ],
)
async def test_history_aggregation_uses_separate_composite_streams(event_type, file_field, metric):
    raw_client = AsyncMock()
    raw_client.search.return_value = {
        "aggregations": {
            "daily": {
                "buckets": [
                    {"key": {"file_id": 11, "local_date": "2026-08-13"}, "doc_count": 7},
                ],
                "after_key": {"file_id": 11, "local_date": "2026-08-13"},
            }
        }
    }
    repository = KnowledgeFulltextEngagementRepositoryImpl(
        daily_client=AsyncMock(),
        raw_client=raw_client,
    )

    page = await repository.aggregate_history_page(
        event_type=event_type,
        after_key={"file_id": 10, "local_date": "2026-08-12"},
        page_size=100,
    )

    kwargs = raw_client.search.await_args.kwargs
    composite = kwargs["aggs"]["daily"]["composite"]
    assert composite["sources"][0] == {"file_id": {"terms": {"field": file_field}}}
    assert composite["after"] == {"file_id": 10, "local_date": "2026-08-12"}
    assert getattr(page.records[0], metric) == 7
    assert page.after_key == {"file_id": 11, "local_date": "2026-08-13"}


async def test_history_daily_metric_initial_upsert_creates_instead_of_noop():
    daily_client = AsyncMock()
    daily_client.bulk.return_value = {
        "items": [{"update": {"_id": "portal_engagement_11_2026-08-13", "status": 201, "result": "created"}}]
    }
    repository = KnowledgeFulltextEngagementRepositoryImpl(
        daily_client=daily_client,
        raw_client=AsyncMock(),
        daily_index="test_portal_engagement_daily",
    )

    changed = await repository.set_daily_metric(
        [KnowledgeFulltextEngagementDaily(file_id=11, local_date="2026-08-13", preview_count=7)],
        metric="preview_count",
        updated_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
    )

    operation = daily_client.bulk.await_args.kwargs["operations"][1]
    script_source = operation["script"]["source"]
    assert "ctx.op != 'create'" in script_source
    assert changed == [11]


class FakeQueue:
    def __init__(self):
        self.cursors = {}
        self.enqueued = []

    async def load_history_cursor(self, stage):
        return self.cursors.get(stage)

    async def save_history_cursor(self, stage, cursor):
        self.cursors[stage] = cursor

    async def enqueue(self, *, file_id, now_epoch):
        self.enqueued.append((file_id, now_epoch))
        return True


async def test_history_rebuild_merges_both_streams_and_zero_fills_existing_documents(monkeypatch):
    statistics_repository = AsyncMock()

    async def aggregate(*, event_type, after_key, **_kwargs):
        metric = "preview_count" if event_type == "portal_document_read" else "download_count"
        if event_type == "portal_document_read" and after_key is None:
            return KnowledgeFulltextEngagementHistoryPage(
                records=[KnowledgeFulltextEngagementDaily(file_id=11, local_date="2026-08-13", **{metric: 2})],
                after_key={"file_id": 11, "local_date": "2026-08-13"},
            )
        if event_type == "portal_document_read":
            assert after_key == {"file_id": 11, "local_date": "2026-08-13"}
            return KnowledgeFulltextEngagementHistoryPage(
                records=[KnowledgeFulltextEngagementDaily(file_id=12, local_date="2026-08-13", **{metric: 1})]
            )
        assert after_key is None
        return KnowledgeFulltextEngagementHistoryPage(
            records=[KnowledgeFulltextEngagementDaily(file_id=11, local_date="2026-08-13", **{metric: 2})]
        )

    statistics_repository.aggregate_history_page.side_effect = aggregate
    statistics_repository.set_daily_metric.return_value = [11]
    statistics_repository.get_totals.return_value = {
        11: KnowledgeFulltextEngagementCounts(file_id=11, preview_count=2, download_count=2),
        12: KnowledgeFulltextEngagementCounts(file_id=12),
    }
    index_repository = AsyncMock()
    index_repository.list_file_ids.return_value = [11, 12]
    index_repository.bulk_update_engagement.return_value = KnowledgeFulltextEngagementBulkResult(updated_ids=[11, 12])
    queue = FakeQueue()
    service = KnowledgeFulltextEngagementService(
        statistics_repository=statistics_repository,
        queue_repository=queue,
        index_repository=index_repository,
    )

    result = await service.rebuild_history(now=datetime(2026, 8, 13, tzinfo=timezone.utc))

    assert result["daily_records"] == 3
    assert statistics_repository.aggregate_history_page.await_count == 3
    index_repository.bulk_update_engagement.assert_awaited_once()
    sent_counts = index_repository.bulk_update_engagement.await_args.args[0]
    assert sent_counts[1] == KnowledgeFulltextEngagementCounts(file_id=12)
    assert queue.cursors == {
        "portal_document_read": {"completed": True},
        "portal_document_download": {"completed": True},
        "fulltext": {"completed": True},
    }

    statistics_repository.reset_mock()
    index_repository.reset_mock()
    await service.rebuild_history(now=datetime(2026, 8, 13, tzinfo=timezone.utc))
    statistics_repository.aggregate_history_page.assert_not_awaited()
    index_repository.list_file_ids.assert_not_awaited()


async def test_history_rebuild_refreshes_daily_index_before_reading_totals():
    events = []
    statistics_repository = AsyncMock()
    statistics_repository.aggregate_history_page.return_value = KnowledgeFulltextEngagementHistoryPage(
        records=[KnowledgeFulltextEngagementDaily(file_id=11, local_date="2026-08-13", preview_count=2)]
    )
    statistics_repository.set_daily_metric.return_value = [11]

    async def refresh_daily():
        events.append("refresh_daily")

    async def get_totals(file_ids):
        events.append("get_totals")
        return {file_id: KnowledgeFulltextEngagementCounts(file_id=file_id, preview_count=2) for file_id in file_ids}

    statistics_repository.refresh_daily.side_effect = refresh_daily
    statistics_repository.get_totals.side_effect = get_totals
    index_repository = AsyncMock()
    index_repository.list_file_ids.return_value = [11]
    index_repository.bulk_update_engagement.return_value = KnowledgeFulltextEngagementBulkResult(updated_ids=[11])
    service = KnowledgeFulltextEngagementService(
        statistics_repository=statistics_repository,
        queue_repository=FakeQueue(),
        index_repository=index_repository,
    )

    await service.rebuild_history(now=datetime(2026, 8, 13, tzinfo=timezone.utc))

    statistics_repository.refresh_daily.assert_awaited_once()
    assert events == ["refresh_daily", "get_totals"]


async def test_recent_reconciliation_uses_three_shanghai_calendar_days():
    statistics_repository = AsyncMock()
    statistics_repository.aggregate_history_page.return_value = KnowledgeFulltextEngagementHistoryPage()
    statistics_repository.set_daily_metric.return_value = []
    service = KnowledgeFulltextEngagementService(
        statistics_repository=statistics_repository,
        queue_repository=FakeQueue(),
        index_repository=AsyncMock(),
    )

    await service.reconcile_recent(now=datetime(2026, 8, 13, 16, 30, tzinfo=timezone.utc))

    assert statistics_repository.aggregate_history_page.await_count == 2
    for call in statistics_repository.aggregate_history_page.await_args_list:
        assert call.kwargs["start_at"].isoformat() == "2026-08-12T00:00:00+08:00"
        assert call.kwargs["end_at"].isoformat() == "2026-08-15T00:00:00+08:00"


async def test_recent_reconciliation_requeues_observed_files_when_daily_values_are_unchanged():
    statistics_repository = AsyncMock()
    statistics_repository.aggregate_history_page.side_effect = [
        KnowledgeFulltextEngagementHistoryPage(
            records=[
                KnowledgeFulltextEngagementDaily(
                    file_id=11,
                    local_date="2026-08-13",
                    preview_count=2,
                )
            ]
        ),
        KnowledgeFulltextEngagementHistoryPage(),
    ]
    statistics_repository.set_daily_metric.return_value = []
    queue = FakeQueue()
    service = KnowledgeFulltextEngagementService(
        statistics_repository=statistics_repository,
        queue_repository=queue,
        index_repository=AsyncMock(),
    )

    result = await service.reconcile_recent(now=datetime(2026, 8, 13, 16, 30, tzinfo=timezone.utc))

    assert result == {
        "pages": 2,
        "records": 1,
        "observed_file_count": 1,
        "changed_file_count": 0,
    }
    assert queue.enqueued == [(11, 1786638600)]
