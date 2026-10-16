from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
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


async def test_first_sync_uses_bootstrap_articles_and_commits_snapshot_watermark():
    now = int(datetime.now(UTC).timestamp())
    client = AsyncMock()
    client.get_information_articles_bootstrap.return_value = InformationArticlesResponse(
        articles=[_article("A", 300), _article("B", 200)],
        total=2,
        page_size=2,
        snapshot_max_create_time=400,
    )
    client.list_all_subscriptions.return_value = [_subscription(now)]
    repo = AsyncMock()
    state = ChannelInfoSource(id="source-A", source_name="A", source_type="website")
    repo.find_by_source_id.return_value = state
    repo.commit_if_unchanged.return_value = True
    es = AsyncMock()
    es.mget_existing_ids.return_value = set()
    es.bulk_index_articles_detailed.return_value = ArticleBulkWriteResult(success_ids={"A", "B"}, failed_ids={})
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
    client.get_information_articles_bootstrap.assert_awaited_once_with("source-A", limit=2)
    client.get_information_articles_page.assert_not_awaited()
    assert repo.commit_if_unchanged.await_args.args[2] == 400


async def test_duplicate_or_unstable_page_is_rejected_without_commit():
    now = int(datetime.now(UTC).timestamp())
    client = AsyncMock()
    client.get_information_articles_page.return_value = InformationArticlesResponse(
        articles=[_article("A", 200), _article("A", 200)], total=2, snapshot_max_create_time=200
    )
    repo = AsyncMock()
    state = ChannelInfoSource(id="source-A", source_name="A", source_type="website", article_cursor_create_time=100)
    repo.find_by_source_id.return_value = state
    service = InformationArticleSyncService(client, repo, AsyncMock())

    result = await service.sync_source(
        _subscription(now),
        MagicMock(refresh=MagicMock(return_value=True)),
        AsyncMock(),
    )

    assert result["result"] == "failed"
    repo.commit_if_unchanged.assert_not_awaited()


async def test_first_sync_rejects_incomplete_bootstrap_response():
    client = AsyncMock()
    client.get_information_articles_bootstrap.return_value = InformationArticlesResponse(
        articles=[_article("A", 300)],
        total=2,
        current_page=1,
        page_size=1,
        snapshot_max_create_time=300,
    )
    repo = AsyncMock()
    service = InformationArticleSyncService(
        client,
        repo,
        AsyncMock(),
        get_conf=lambda: IntelligenceCenterConf(information_initial_article_limit=20),
    )

    with pytest.raises(RuntimeError, match="bootstrap article response was incomplete"):
        await service._bootstrap(
            _subscription(int(datetime.now(UTC).timestamp())),
            MagicMock(refresh=MagicMock(return_value=True)),
            AsyncMock(),
        )

    repo.commit_if_unchanged.assert_not_awaited()
