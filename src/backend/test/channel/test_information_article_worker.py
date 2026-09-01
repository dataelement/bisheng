from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.core.config.settings import IntelligenceCenterConf
from bisheng.core.external.bisheng_information_client.response_schema import InformationSubscriptionItem
from bisheng.worker.information import article as article_mod


def _item(source_id: str):
    return InformationSubscriptionItem(
        id=source_id,
        source_id=f"external-{source_id}",
        business_type="website",
        name=source_id,
    )


def test_article_dispatcher_uses_random_countdown():
    with (
        patch.object(article_mod, "_jitter_seconds", return_value=600),
        patch.object(article_mod.random, "randint", return_value=321),
        patch.object(article_mod.sync_information_articles, "apply_async") as apply_async,
    ):
        article_mod.dispatch_information_article_poll.run()

    apply_async.assert_called_once_with(countdown=321)


async def test_public_article_worker_processes_each_remote_source_once_and_isolates_failure():
    client = AsyncMock()
    client.list_all_subscriptions.return_value = [_item("A"), _item("B")]
    with (
        patch.object(article_mod, "get_bisheng_information_client", new=AsyncMock(return_value=client)),
        patch.object(article_mod, "_sync_one_source", new=AsyncMock(side_effect=[RuntimeError("A"), None])) as sync,
    ):
        await article_mod._sync_information_articles_async()

    assert [call.args[1].id for call in sync.await_args_list] == ["A", "B"]


async def test_disabled_knowledge_delivery_does_not_publish_route_task():
    client = SimpleNamespace(conf=IntelligenceCenterConf(information_knowledge_delivery_enabled=False))
    with patch(
        "bisheng.worker.information.knowledge_delivery.route_new_information_articles.apply_async"
    ) as apply_async:
        await article_mod._dispatch_new_articles(client, "source-A", ["article-A"], 1)

    apply_async.assert_not_called()
