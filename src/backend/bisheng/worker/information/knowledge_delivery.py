from contextlib import asynccontextmanager

from loguru import logger

from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


class InformationTaskTenantContextError(RuntimeError):
    """Information config delivery requires matching header and payload tenants."""


@bisheng_celery.task
def route_new_information_articles(source_id: str, article_ids: list[str], detected_at: int) -> None:
    run_async_task(lambda: _route_new_information_articles_async(source_id, article_ids, detected_at))


@bisheng_celery.task(bind=True)
def deliver_information_articles_to_config(
    self,
    tenant_id: int,
    sync_config_id: str,
    article_ids: list[str],
    detected_at: int,
) -> None:
    headers = getattr(self.request, "headers", None) or {}
    header_tenant_id = headers.get("tenant_id")
    current = get_current_tenant_id()
    if header_tenant_id is None or int(header_tenant_id) != int(tenant_id) or current != int(tenant_id):
        raise InformationTaskTenantContextError("information delivery tenant header, context and payload must match")
    run_async_task(
        lambda: _deliver_information_articles_to_config_async(
            tenant_id,
            sync_config_id,
            article_ids,
            detected_at,
        )
    )


async def _active_tenant_ids() -> list[int]:
    from bisheng.worker.information.reconcile import _active_tenant_ids as load_active_tenant_ids

    return await load_active_tenant_ids()


async def _route_new_information_articles_async(
    source_id: str,
    article_ids: list[str],
    detected_at: int,
) -> None:
    for tenant_id in await _active_tenant_ids():
        token = set_current_tenant_id(tenant_id)
        try:
            async with _service_session(include_channel_service=False) as service:

                async def dispatch(
                    config_id: str,
                    selected_ids: list[str],
                    batch_detected_at: int,
                    target_tenant_id: int = tenant_id,
                ) -> None:
                    deliver_information_articles_to_config.apply_async(
                        args=(target_tenant_id, config_id, selected_ids, batch_detected_at)
                    )

                await service.route_current_tenant(source_id, article_ids, detected_at, dispatch)
        except Exception:
            logger.exception(
                "information knowledge route tenant failed tenant_id={} source_id={}",
                tenant_id,
                source_id,
            )
        finally:
            current_tenant_id.reset(token)


async def _deliver_information_articles_to_config_async(
    tenant_id: int,
    sync_config_id: str,
    article_ids: list[str],
    detected_at: int,
) -> None:
    async with _service_session(include_channel_service=True) as service:
        await service.deliver_to_config(tenant_id, sync_config_id, article_ids, detected_at)


@asynccontextmanager
async def _service_session(*, include_channel_service: bool):
    from bisheng.channel.domain.repositories.implementations.article_read_repository_impl import (
        ArticleReadRepositoryImpl,
    )
    from bisheng.channel.domain.repositories.implementations.channel_info_source_repository_impl import (
        ChannelInfoSourceRepositoryImpl,
    )
    from bisheng.channel.domain.repositories.implementations.channel_knowledge_sync_repository_impl import (
        ChannelKnowledgeSyncRepositoryImpl,
    )
    from bisheng.channel.domain.repositories.implementations.channel_repository_impl import ChannelRepositoryImpl
    from bisheng.channel.domain.services.article_es_service import ArticleEsService
    from bisheng.channel.domain.services.channel_service import ChannelService
    from bisheng.channel.domain.services.information_knowledge_delivery_service import (
        InformationKnowledgeDeliveryService,
    )
    from bisheng.common.repositories.implementations.space_channel_member_repository_impl import (
        SpaceChannelMemberRepositoryImpl,
    )
    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        channel_repository = ChannelRepositoryImpl(session)
        article_service = ArticleEsService()
        channel_service = None
        if include_channel_service:
            channel_service = ChannelService(
                channel_repository=channel_repository,
                space_channel_member_repository=SpaceChannelMemberRepositoryImpl(session),
                channel_info_source_repository=ChannelInfoSourceRepositoryImpl(session),
                article_es_service=article_service,
                article_read_repository=ArticleReadRepositoryImpl(session),
            )
        yield InformationKnowledgeDeliveryService(
            channel_repository,
            ChannelKnowledgeSyncRepositoryImpl(session),
            article_service,
            channel_service=channel_service,
        )
