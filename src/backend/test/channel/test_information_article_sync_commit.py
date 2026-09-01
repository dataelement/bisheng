from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from bisheng.channel.domain.models.information_article_sync_state import InformationArticleSyncState
from bisheng.channel.domain.services.article_es_service import ArticleBulkWriteResult
from bisheng.channel.domain.services.information_article_sync_service import InformationArticleSyncService
from bisheng.core.external.bisheng_information_client.response_schema import (
    ArticleInfo,
    InformationArticlesResponse,
    InformationSubscriptionItem,
)


async def test_only_previously_absent_success_ids_are_dispatched_and_committed():
    now = int(datetime.now(UTC).timestamp())
    subscription = InformationSubscriptionItem(
        id="source-A",
        source_id="external-A",
        business_type="website",
        name="A",
        last_sync_at=now,
        article_list_updated_at=now,
    )
    page = InformationArticlesResponse(
        articles=[
            ArticleInfo(id="A", title="A", original_url="https://example.test/A", create_time=200),
            ArticleInfo(id="B", title="B", original_url="https://example.test/B", create_time=100),
        ],
        total=2,
    )
    client = AsyncMock()
    client.get_information_articles_page.return_value = page
    client.list_all_subscriptions.return_value = [subscription]
    state = InformationArticleSyncState(source_id="source-A", article_cursor_create_time=100)
    repo = AsyncMock()
    repo.find_by_source_id.return_value = state
    repo.commit_if_unchanged.return_value = True
    es = AsyncMock()
    es.mget_existing_ids.return_value = {"B"}
    es.bulk_index_articles_detailed.return_value = ArticleBulkWriteResult(success_ids={"A", "B"}, failed_ids={})
    dispatch = AsyncMock()
    lock = MagicMock(refresh=MagicMock(return_value=True))
    service = InformationArticleSyncService(client, repo, es)

    result = await service.sync_source(subscription, lock, dispatch)

    dispatch.assert_awaited_once()
    assert dispatch.await_args.args[0] == "source-A"
    assert dispatch.await_args.args[1] == ["A"]
    es.refresh_index.assert_awaited_once()
    repo.commit_if_unchanged.assert_awaited_once()
    assert result["new_article_ids"] == ["A"]


async def test_partial_bulk_failure_dispatches_successes_but_keeps_state_uncommitted():
    now = int(datetime.now(UTC).timestamp())
    subscription = InformationSubscriptionItem(
        id="source-A",
        source_id="external-A",
        business_type="website",
        name="A",
        last_sync_at=now,
        article_list_updated_at=now,
    )
    client = AsyncMock()
    client.get_information_articles_page.return_value = InformationArticlesResponse(
        articles=[
            ArticleInfo(id="B", title="B", original_url="https://example.test/B", create_time=200),
            ArticleInfo(id="A", title="A", original_url="https://example.test/A", create_time=100),
        ],
        total=2,
    )
    state = InformationArticleSyncState(source_id="source-A", article_cursor_create_time=100)
    repo = AsyncMock()
    repo.find_by_source_id.return_value = state
    es = AsyncMock()
    es.mget_existing_ids.return_value = set()
    es.bulk_index_articles_detailed.return_value = ArticleBulkWriteResult(
        success_ids={"B"},
        failed_ids={"A": "failed"},
    )
    service = InformationArticleSyncService(client, repo, es)
    dispatch = AsyncMock()

    result = await service.sync_source(
        subscription,
        MagicMock(refresh=MagicMock(return_value=True)),
        dispatch,
    )

    assert result["result"] == "failed"
    dispatch.assert_awaited_once()
    assert dispatch.await_args.args[1] == ["B"]
    es.refresh_index.assert_awaited_once()
    repo.commit_if_unchanged.assert_not_awaited()


async def test_lock_loss_after_write_keeps_state_uncommitted():
    now = int(datetime.now(UTC).timestamp())
    subscription = InformationSubscriptionItem(
        id="source-A",
        source_id="external-A",
        business_type="website",
        name="A",
        last_sync_at=now,
        article_list_updated_at=now,
    )
    client = AsyncMock()
    client.get_information_articles_page.return_value = InformationArticlesResponse(
        articles=[ArticleInfo(id="A", title="A", original_url="https://example.test/A", create_time=100)],
        total=1,
    )
    client.list_all_subscriptions.return_value = [subscription]
    state = InformationArticleSyncState(source_id="source-A", article_cursor_create_time=100)
    repo = AsyncMock()
    repo.find_by_source_id.return_value = state
    es = AsyncMock()
    es.mget_existing_ids.return_value = set()
    es.bulk_index_articles_detailed.return_value = ArticleBulkWriteResult(success_ids={"A"}, failed_ids={})
    dispatch = AsyncMock()
    lock = MagicMock(refresh=MagicMock(side_effect=[True, False]))
    service = InformationArticleSyncService(client, repo, es)

    result = await service.sync_source(subscription, lock, dispatch)

    assert result["result"] == "lock_lost"
    dispatch.assert_awaited_once()
    repo.commit_if_unchanged.assert_not_awaited()


async def test_dispatch_failure_does_not_rollback_es_or_public_state():
    now = int(datetime.now(UTC).timestamp())
    subscription = InformationSubscriptionItem(
        id="source-A",
        source_id="external-A",
        business_type="website",
        name="A",
        last_sync_at=now,
        article_list_updated_at=now,
    )
    client = AsyncMock()
    client.get_information_articles_page.return_value = InformationArticlesResponse(
        articles=[ArticleInfo(id="A", title="A", original_url="https://example.test/A", create_time=100)],
        total=1,
    )
    client.list_all_subscriptions.return_value = [subscription]
    state = InformationArticleSyncState(source_id="source-A", article_cursor_create_time=100)
    repo = AsyncMock()
    repo.find_by_source_id.return_value = state
    repo.commit_if_unchanged.return_value = True
    es = AsyncMock()
    es.mget_existing_ids.return_value = set()
    es.bulk_index_articles_detailed.return_value = ArticleBulkWriteResult(success_ids={"A"}, failed_ids={})
    dispatch = AsyncMock(side_effect=RuntimeError("broker unavailable"))
    service = InformationArticleSyncService(client, repo, es)

    result = await service.sync_source(
        subscription,
        MagicMock(refresh=MagicMock(return_value=True)),
        dispatch,
    )

    assert result["result"] == "success"
    assert result["new_article_ids"] == ["A"]
    repo.commit_if_unchanged.assert_awaited_once()
