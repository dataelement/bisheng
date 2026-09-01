from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.channel.domain.models.information_article_sync_state import InformationArticleSyncState
from bisheng.channel.domain.services.article_es_service import ArticleBulkWriteResult
from bisheng.channel.domain.services.information_article_sync_service import InformationArticleSyncService
from bisheng.core.config.settings import IntelligenceCenterConf
from bisheng.core.external.bisheng_information_client.response_schema import (
    ArticleInfo,
    InformationArticlesResponse,
    InformationSubscriptionItem,
)


def _article(article_id: str, timestamp: int) -> ArticleInfo:
    return ArticleInfo(id=article_id, title=article_id, original_url="https://example.test", create_time=timestamp)


def _subscription(watermark: int) -> InformationSubscriptionItem:
    return InformationSubscriptionItem(
        id="source-A",
        source_id="external-A",
        business_type="website",
        name="A",
        last_sync_at=watermark,
        article_list_updated_at=watermark,
    )


async def test_first_sync_freezes_nth_time_then_scans_inclusive_boundary():
    now = int(datetime.now(UTC).timestamp())
    client = AsyncMock()
    client.get_information_articles_page.side_effect = [
        InformationArticlesResponse(articles=[_article("A", 300), _article("B", 200)], total=3, page_size=2),
        InformationArticlesResponse(
            articles=[_article("A", 300), _article("C", 200), _article("B", 200)], total=3, page_size=100
        ),
    ]
    client.list_all_subscriptions.return_value = [_subscription(now)]
    repo = AsyncMock()
    repo.find_by_source_id.return_value = None
    boundary = InformationArticleSyncState(source_id="source-A", article_cursor_create_time=200)
    repo.create_initial_boundary_if_absent.return_value = boundary
    repo.commit_if_unchanged.return_value = True
    es = AsyncMock()
    es.mget_existing_ids.return_value = set()
    es.bulk_index_articles_detailed.return_value = ArticleBulkWriteResult(success_ids={"A", "B", "C"}, failed_ids={})
    service = InformationArticleSyncService(
        client,
        repo,
        es,
        get_conf=lambda: IntelligenceCenterConf(information_initial_article_limit=2),
    )

    result = await service.sync_source(
        _subscription(now),
        MagicMock(refresh=MagicMock(return_value=True)),
        AsyncMock(),
    )

    assert result["result"] == "success"
    repo.create_initial_boundary_if_absent.assert_awaited_once_with("source-A", 200)
    assert client.get_information_articles_page.await_args_list[0].kwargs["min_create_time"] is None
    assert client.get_information_articles_page.await_args_list[1].kwargs["min_create_time"] == 200
    assert repo.commit_if_unchanged.await_args.args[2] == 300


async def test_duplicate_or_unstable_page_is_rejected_without_commit():
    now = int(datetime.now(UTC).timestamp())
    client = AsyncMock()
    client.get_information_articles_page.return_value = InformationArticlesResponse(
        articles=[_article("A", 200), _article("A", 200)], total=2
    )
    repo = AsyncMock()
    state = InformationArticleSyncState(source_id="source-A", article_cursor_create_time=100)
    repo.find_by_source_id.return_value = state
    service = InformationArticleSyncService(client, repo, AsyncMock())

    result = await service.sync_source(
        _subscription(now),
        MagicMock(refresh=MagicMock(return_value=True)),
        AsyncMock(),
    )

    assert result["result"] == "failed"
    repo.commit_if_unchanged.assert_not_awaited()


async def test_first_sync_rejects_a_page_that_does_not_cover_configured_limit():
    client = AsyncMock()
    client.get_information_articles_page.return_value = InformationArticlesResponse(
        articles=[_article("A", 300)],
        total=100,
        current_page=1,
        page_size=1,
    )
    repo = AsyncMock()
    service = InformationArticleSyncService(
        client,
        repo,
        AsyncMock(),
        get_conf=lambda: IntelligenceCenterConf(information_initial_article_limit=20),
    )

    with pytest.raises(RuntimeError, match="initial article page was incomplete"):
        await service._ensure_initial_boundary("source-A", None)

    repo.create_initial_boundary_if_absent.assert_not_awaited()
