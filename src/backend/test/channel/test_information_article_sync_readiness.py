from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from bisheng.channel.domain.models.information_article_sync_state import InformationArticleSyncState
from bisheng.channel.domain.services.information_article_sync_service import InformationArticleSyncService
from bisheng.core.config.settings import IntelligenceCenterConf
from bisheng.core.external.bisheng_information_client.response_schema import InformationSubscriptionItem


def _subscription(*, last_sync_at: int | None, article_updated_at: int | None):
    return InformationSubscriptionItem(
        id="source-A",
        source_id="external-A",
        business_type="website",
        name="A",
        last_sync_at=last_sync_at,
        article_list_updated_at=article_updated_at,
    )


def _service(state):
    client = AsyncMock()
    repo = AsyncMock()
    repo.find_by_source_id.return_value = state
    service = InformationArticleSyncService(
        client,
        repo,
        AsyncMock(),
        get_conf=lambda: IntelligenceCenterConf(information_business_timezone="Asia/Shanghai"),
    )
    return service, client, repo


async def test_remote_not_ready_does_not_request_articles_or_advance_state():
    yesterday = int((datetime.now(UTC) - timedelta(days=1)).timestamp())
    service, client, repo = _service(None)

    result = await service.sync_source(
        _subscription(last_sync_at=yesterday, article_updated_at=yesterday),
        MagicMock(refresh=MagicMock(return_value=True)),
        AsyncMock(),
    )

    assert result["result"] == "not_ready"
    client.get_information_articles_page.assert_not_awaited()
    repo.commit_if_unchanged.assert_not_awaited()


async def test_equal_watermarks_skip_article_request():
    now = int(datetime.now(UTC).timestamp())
    state = InformationArticleSyncState(
        source_id="source-A",
        article_cursor_create_time=100,
        processed_remote_sync_at=now,
        processed_article_list_updated_at=now,
    )
    service, client, repo = _service(state)

    result = await service.sync_source(
        _subscription(last_sync_at=now, article_updated_at=now),
        MagicMock(refresh=MagicMock(return_value=True)),
        AsyncMock(),
    )

    assert result["result"] == "no_change"
    client.get_information_articles_page.assert_not_awaited()
    repo.commit_if_unchanged.assert_not_awaited()


async def test_only_remote_sync_watermark_change_commits_without_article_request():
    now = int(datetime.now(UTC).timestamp())
    state = InformationArticleSyncState(
        source_id="source-A",
        article_cursor_create_time=100,
        processed_remote_sync_at=now - 60,
        processed_article_list_updated_at=now,
    )
    service, client, repo = _service(state)
    repo.commit_if_unchanged.return_value = True

    result = await service.sync_source(
        _subscription(last_sync_at=now, article_updated_at=now),
        MagicMock(refresh=MagicMock(return_value=True)),
        AsyncMock(),
    )

    assert result["result"] == "checked"
    client.get_information_articles_page.assert_not_awaited()
    repo.commit_if_unchanged.assert_awaited_once_with("source-A", state, 100, now, now)


async def test_null_article_watermark_is_unknown_and_still_requests_articles():
    now = int(datetime.now(UTC).timestamp())
    state = InformationArticleSyncState(
        source_id="source-A",
        article_cursor_create_time=100,
        processed_remote_sync_at=now - 60,
        processed_article_list_updated_at=None,
    )
    service, client, repo = _service(state)
    client.get_information_articles_page.return_value = MagicMock(
        articles=[],
        total=0,
        current_page=1,
    )
    client.list_all_subscriptions.return_value = [
        _subscription(last_sync_at=now, article_updated_at=None),
    ]
    repo.commit_if_unchanged.return_value = True

    result = await service.sync_source(
        _subscription(last_sync_at=now, article_updated_at=None),
        MagicMock(refresh=MagicMock(return_value=True)),
        AsyncMock(),
    )

    assert result["result"] == "success"
    client.get_information_articles_page.assert_awaited_once()
    repo.commit_if_unchanged.assert_awaited_once_with("source-A", state, 100, now, None)
