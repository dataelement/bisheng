from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from bisheng.channel.domain.models.information_article_sync_state import InformationArticleSyncState
from bisheng.channel.domain.services.article_es_service import ArticleBulkWriteResult
from bisheng.channel.domain.services.information_article_sync_service import InformationArticleSyncService
from bisheng.channel.domain.services.information_knowledge_delivery_service import (
    InformationKnowledgeDeliveryService,
)
from bisheng.channel.domain.services.information_subscription_reconcile_service import (
    DesiredSubscriptionSnapshot,
    InformationSubscriptionReconcileService,
)
from bisheng.core.config.settings import IntelligenceCenterConf
from bisheng.core.external.bisheng_information_client.response_schema import (
    ArticleInfo,
    InformationArticlesResponse,
    InformationSubscriptionItem,
)

SOURCE_ID = "source-shared"


def _subscription(last_sync_at: int, article_list_updated_at: int) -> InformationSubscriptionItem:
    return InformationSubscriptionItem(
        id=SOURCE_ID,
        source_id="external-shared",
        business_type="website",
        name="Shared source",
        last_sync_at=last_sync_at,
        article_list_updated_at=article_list_updated_at,
    )


class FakeInformationClient:
    def __init__(self, subscription: InformationSubscriptionItem, articles: list[ArticleInfo]):
        self.conf = IntelligenceCenterConf()
        self.subscription = subscription
        self.articles = articles
        self.subscribed = False
        self.article_page_calls = 0

    async def list_all_subscriptions(self, page_size: int = 100) -> list[InformationSubscriptionItem]:
        del page_size
        return [self.subscription] if self.subscribed else []

    async def subscribe_one(self, source_id: str) -> None:
        assert source_id == SOURCE_ID
        self.subscribed = True

    async def unsubscribe_one(self, source_id: str) -> None:
        assert source_id == SOURCE_ID
        self.subscribed = False

    async def get_information_articles_page(
        self,
        information_id: str,
        *,
        min_create_time: int | None,
        page: int,
        page_size: int,
    ) -> InformationArticlesResponse:
        assert information_id == SOURCE_ID
        assert page == 1
        assert page_size in {20, 100}
        self.article_page_calls += 1
        articles = [
            article
            for article in self.articles
            if min_create_time is None or int(article.create_time) >= min_create_time
        ]
        return InformationArticlesResponse(
            articles=articles,
            total=len(articles),
            current_page=1,
            page_size=page_size,
        )


class FakeMetadataRepository:
    def __init__(self):
        self.ids: set[str] = set()

    async def upsert_metadata(self, sources) -> None:
        self.ids.update(source.id for source in sources)


class FakeStateRepository:
    def __init__(self):
        self.state: InformationArticleSyncState | None = None

    async def find_by_source_id(self, source_id: str) -> InformationArticleSyncState | None:
        assert source_id == SOURCE_ID
        return self.state

    async def create_initial_boundary_if_absent(
        self,
        source_id: str,
        cursor: int | None,
    ) -> InformationArticleSyncState:
        if self.state is None:
            self.state = InformationArticleSyncState(
                source_id=source_id,
                article_cursor_create_time=cursor,
            )
        elif self.state.article_cursor_create_time is None and cursor is not None:
            self.state.article_cursor_create_time = cursor
        return self.state

    async def commit_if_unchanged(
        self,
        source_id: str,
        expected_state: InformationArticleSyncState,
        next_cursor: int | None,
        remote_sync_at: int | None,
        article_list_updated_at: int | None,
    ) -> bool:
        if self.state is not expected_state or self.state.source_id != source_id:
            return False
        self.state.article_cursor_create_time = next_cursor
        self.state.processed_remote_sync_at = remote_sync_at
        self.state.processed_article_list_updated_at = article_list_updated_at
        return True


class FakeArticleStore:
    def __init__(self):
        self.ids: set[str] = set()
        self.refresh_count = 0

    async def mget_existing_ids(self, article_ids: list[str]) -> set[str]:
        return self.ids.intersection(article_ids)

    async def bulk_index_articles_detailed(self, articles_by_id) -> ArticleBulkWriteResult:
        success_ids = set(articles_by_id)
        self.ids.update(success_ids)
        return ArticleBulkWriteResult(success_ids=success_ids, failed_ids={})

    async def refresh_index(self) -> None:
        self.refresh_count += 1


class AlwaysOwnedLock:
    @staticmethod
    def refresh() -> bool:
        return True


async def test_shared_source_reconciles_once_then_late_articles_route_to_each_tenant():
    """AC-01/11/12/15/23/24/25: shared source converges and routes one public batch."""
    now = int(datetime.now(UTC).timestamp())
    yesterday = now - 86400
    articles = [
        ArticleInfo(
            id="article-2",
            title="Important update",
            original_url="https://example.test/2",
            create_time=200,
        ),
        ArticleInfo(
            id="article-1",
            title="General update",
            original_url="https://example.test/1",
            create_time=200,
        ),
    ]
    client = FakeInformationClient(_subscription(yesterday, 1), articles)
    metadata = FakeMetadataRepository()
    desired = DesiredSubscriptionSnapshot(ids=frozenset({SOURCE_ID}), complete=True)
    reconcile = InformationSubscriptionReconcileService(client, metadata)

    reconcile_result = await reconcile.reconcile(desired, lambda: _return(desired))

    assert reconcile_result["result"] == "converged"
    assert reconcile_result["subscribed"] == 1
    assert metadata.ids == {SOURCE_ID}

    state_repository = FakeStateRepository()
    article_store = FakeArticleStore()
    public_batches: list[tuple[str, list[str], int]] = []
    article_sync = InformationArticleSyncService(
        client,
        state_repository,
        article_store,
        get_conf=IntelligenceCenterConf,
    )

    not_ready = await article_sync.sync_source(
        client.subscription,
        AlwaysOwnedLock(),
        lambda source_id, article_ids, detected_at: public_batches.append((source_id, article_ids, detected_at)),
    )
    assert not_ready["result"] == "not_ready"
    assert client.article_page_calls == 0

    client.subscription = _subscription(now, 2)
    synced = await article_sync.sync_source(
        client.subscription,
        AlwaysOwnedLock(),
        lambda source_id, article_ids, detected_at: public_batches.append((source_id, article_ids, detected_at)),
    )
    assert synced["result"] == "success"
    assert synced["new_article_ids"] == ["article-1", "article-2"]
    assert article_store.ids == {"article-1", "article-2"}
    assert len(public_batches) == 1

    tenant_dispatches: list[tuple[int, str, list[str]]] = []
    detected_at = public_batches[0][2]
    for tenant_id, sub_channel_name in ((101, None), (202, "important")):
        channel = SimpleNamespace(
            id=f"channel-{tenant_id}",
            source_list=[SOURCE_ID],
            filter_rules=[{"channel_type": "sub", "name": "important", "keywords": ["Important"]}],
        )
        config = SimpleNamespace(
            id=f"config-{tenant_id}",
            channel_id=channel.id,
            sub_channel_name=sub_channel_name,
            is_enabled=True,
            create_time=datetime.now() - timedelta(minutes=5),
            update_time=datetime.now() - timedelta(minutes=5),
        )
        channel_repository = SimpleNamespace(
            find_channels_referencing_source=lambda _source_id, value=channel: _return([value])
        )
        config_repository = SimpleNamespace(
            find_enabled_by_channel_ids=lambda _channel_ids, value=config: _return([value])
        )
        matcher = SimpleNamespace(
            match_article_ids_sync=lambda article_ids, _source_ids, _groups: [
                article_id for article_id in article_ids if article_id == "article-2"
            ]
        )
        routing = InformationKnowledgeDeliveryService(channel_repository, config_repository, matcher)
        await routing.route_current_tenant(
            SOURCE_ID,
            public_batches[0][1],
            detected_at,
            lambda config_id, article_ids, _detected_at, tenant=tenant_id: tenant_dispatches.append(
                (tenant, config_id, article_ids)
            ),
        )

    assert tenant_dispatches == [
        (101, "config-101", ["article-1", "article-2"]),
        (202, "config-202", ["article-2"]),
    ]

    no_change = await article_sync.sync_source(
        client.subscription,
        AlwaysOwnedLock(),
        lambda *_args: public_batches.append(("unexpected", [], 0)),
    )
    assert no_change["result"] == "no_change"
    assert len(public_batches) == 1


async def test_delivery_failure_is_terminal_and_disabled_routing_does_not_backfill():
    """AC-27/28/31/32: per-article failure continues without retry or later backfill."""
    detected_at = int(datetime.now(UTC).timestamp())
    channel = SimpleNamespace(id="channel-1", source_list=[SOURCE_ID], filter_rules=[])
    config = SimpleNamespace(
        id="config-1",
        channel_id=channel.id,
        sub_channel_name=None,
        is_enabled=True,
        create_time=datetime.now() - timedelta(minutes=5),
        update_time=datetime.now() - timedelta(minutes=5),
        user_id=1,
        knowledge_space_id="1",
        folder_id=None,
    )

    class ChannelService:
        def __init__(self):
            self.calls: list[str] = []

        async def add_articles_to_knowledge_space(self, req, _user, request=None, **kwargs):
            del request, kwargs
            article_id = req.article_ids[0]
            self.calls.append(article_id)
            if article_id == "article-1":
                raise RuntimeError("terminal import failure")

    channel_service = ChannelService()
    channel_repository = SimpleNamespace(find_by_id=lambda _channel_id: _return(channel))
    config_repository = SimpleNamespace(find_by_id=lambda _config_id: _return(config))
    delivery = InformationKnowledgeDeliveryService(
        channel_repository,
        config_repository,
        SimpleNamespace(),
        channel_service=channel_service,
    )

    result = await delivery.deliver_to_config(
        101,
        config.id,
        ["article-1", "article-2"],
        detected_at,
    )

    assert channel_service.calls == ["article-1", "article-2"]
    assert result == {"result": "completed", "accepted": 1, "failed": {"system_failed": 1}}

    disabled_dispatches: list[tuple] = []
    disabled_routing = InformationKnowledgeDeliveryService(
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        get_conf=lambda: IntelligenceCenterConf(information_knowledge_delivery_enabled=False),
    )
    disabled = await disabled_routing.route_current_tenant(
        SOURCE_ID,
        ["article-1", "article-2"],
        detected_at,
        lambda *args: disabled_dispatches.append(args),
    )
    assert disabled["result"] == "disabled"
    assert disabled_dispatches == []
    assert channel_service.calls == ["article-1", "article-2"]


async def _return(value):
    return value
