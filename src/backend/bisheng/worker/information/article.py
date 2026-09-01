import random

from loguru import logger

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.external.bisheng_information_client.bisheng_information_manager import (
    get_bisheng_information_client,
)
from bisheng.core.external.bisheng_information_client.response_schema import InformationSubscriptionItem
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.information.redis_lock import InformationRedisLock
from bisheng.worker.main import bisheng_celery


def _jitter_seconds() -> int:
    from bisheng.common.services.config_service import settings

    return settings.get_intelligence_center_conf().information_sync_jitter_seconds


@bisheng_celery.task
def dispatch_information_article_poll() -> None:
    sync_information_articles.apply_async(countdown=random.randint(0, _jitter_seconds()))


@bisheng_celery.task
def sync_information_articles() -> None:
    run_async_task(_sync_information_articles_async)


async def _sync_information_articles_async() -> None:
    client = await get_bisheng_information_client()
    try:
        subscriptions = await client.list_all_subscriptions()
    except Exception:
        logger.exception("information article sync remote subscription snapshot failed")
        return
    seen: set[str] = set()
    for subscription in subscriptions:
        if subscription.id in seen:
            continue
        seen.add(subscription.id)
        try:
            await _sync_one_source(client, subscription)
        except Exception:
            logger.exception("information article worker source failed source_id={}", subscription.id)


def _new_source_lock(source_id: str) -> InformationRedisLock:
    from bisheng.core.cache.redis_manager import get_redis_client_sync

    return InformationRedisLock(
        get_redis_client_sync().connection,
        f"information:article-sync:{source_id}",
        ttl_seconds=7200,
    )


async def _sync_one_source(client, subscription: InformationSubscriptionItem) -> None:
    from bisheng.channel.domain.repositories.implementations.information_article_sync_state_repository_impl import (
        InformationArticleSyncStateRepositoryImpl,
    )
    from bisheng.channel.domain.services.article_es_service import ArticleEsService
    from bisheng.channel.domain.services.information_article_sync_service import InformationArticleSyncService
    from bisheng.core.database import get_async_db_session

    lock = _new_source_lock(subscription.id)
    if not lock.acquire():
        logger.warning(
            "information article source skipped source_id={} redis_available={}",
            subscription.id,
            lock.redis_available,
        )
        return
    article_service = ArticleEsService()

    async def dispatch(source_id: str, article_ids: list[str], detected_at: int) -> None:
        await _dispatch_new_articles(client, source_id, article_ids, detected_at)

    try:
        async with get_async_db_session() as session:
            service = InformationArticleSyncService(
                client,
                InformationArticleSyncStateRepositoryImpl(session),
                article_service,
            )
            result = await service.sync_source(subscription, lock, dispatch)
        if result["written"]:
            await _update_channel_display_time(subscription.id, article_service)
    finally:
        lock.release()


async def _dispatch_new_articles(
    client,
    source_id: str,
    article_ids: list[str],
    detected_at: int,
) -> None:
    if not client.conf.information_knowledge_delivery_enabled:
        return
    from bisheng.worker.information.knowledge_delivery import route_new_information_articles

    route_new_information_articles.apply_async(args=(source_id, article_ids, detected_at))


async def _update_channel_display_time(source_id: str, article_service) -> None:
    from bisheng.channel.domain.repositories.implementations.channel_repository_impl import ChannelRepositoryImpl
    from bisheng.channel.domain.services.channel_service import ChannelService
    from bisheng.core.database import get_async_db_session
    from bisheng.worker.information.reconcile import _active_tenant_ids

    for tenant_id in await _active_tenant_ids():
        token = set_current_tenant_id(tenant_id)
        try:
            async with get_async_db_session() as session:
                repository = ChannelRepositoryImpl(session)
                channels = await repository.find_channels_referencing_source(source_id)
                service = ChannelService(
                    channel_repository=repository,
                    space_channel_member_repository=None,
                    channel_info_source_repository=None,
                    article_es_service=article_service,
                )
                await service.update_channels_latest_article_time(channels)
        except Exception:
            logger.exception(
                "information article channel display update failed tenant_id={} source_id={}",
                tenant_id,
                source_id,
            )
        finally:
            current_tenant_id.reset(token)
