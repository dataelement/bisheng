from datetime import datetime

from loguru import logger
from sqlalchemy import func
from sqlmodel import select

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
from bisheng.channel.domain.repositories.implementations.channel_info_source_repository_impl import \
    ChannelInfoSourceRepositoryImpl
from bisheng.channel.domain.schemas.article_schema import ArticleDocument
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.core.database import get_sync_db_session
from bisheng.core.external.bisheng_information_client.bisheng_information_manager import \
    get_bisheng_information_client_sync
from bisheng.core.logger import trace_id_var
from bisheng.utils import generate_uuid
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task
def sync_information_article(information_id: str = None):
    trace_id_var.set(f"sync_all_information_articles_{generate_uuid()}")
    logger.debug("Starting to sync information articles for all sources.")
    article_service = ArticleEsService()
    article_service.ensure_index_sync()
    with get_sync_db_session() as session:
        channel_info_repository = ChannelInfoSourceRepositoryImpl(session)
        page, page_size = 1, 1000
        while True:
            information_list = channel_info_repository.get_by_page(information_id, page, page_size)
            if not information_list:
                break
            for one in information_list:
                try:
                    logger.debug(f"Syncing information for {one.id} - {one.source_name}")
                    _sync_one_information_article(one, article_service)
                except Exception as e:
                    logger.exception(f"Failed to sync information article for source {one.id}: {e}")
            page += 1
    logger.debug("Finished syncing information articles for all sources.")

    # Update latest_article_update_time for channels
    if information_id is None:
        # Update all channels
        logger.debug("Updating latest_article_update_time for all channels.")
        _update_channel_latest_article_update_time()
    else:
        # Update only channels that use this information source
        logger.debug(f"Updating latest_article_update_time for channels using information_id={information_id}.")
        _update_channels_by_source_id(information_id)


def _update_channels_by_source_id(source_id: str):
    """Update latest_article_update_time for channels that use the specified source_id."""
    with get_sync_db_session() as session:
        # Query channels whose source_list contains the source_id
        channels = session.exec(
            select(Channel).where(func.json_contains(Channel.source_list, f'"{source_id}"'))
        ).all()

        if not channels:
            logger.debug(f"No channels found using source_id={source_id}.")
            return

        logger.debug(f"Found {len(channels)} channels using source_id={source_id}.")
        updated_count = ChannelService.update_channels_latest_article_time_sync(list(channels))
        logger.debug(f"Updated latest_article_update_time for {updated_count} channels.")


def _sync_one_information_article(information: ChannelInfoSource, article_service: ArticleEsService):
    latest_create_time = article_service.get_source_latest_article_time_sync(source_id=information.id)
    if latest_create_time:
        latest_create_time = datetime.fromisoformat(latest_create_time).timestamp()

    information_client = get_bisheng_information_client_sync()

    page, page_size, current = 1, 10, 0
    while True:
        resp = information_client.get_information_articles(information.id, False,
                                                           min_create_time=latest_create_time,
                                                           page=page,
                                                           page_size=page_size)
        articles = []
        doc_ids = []
        for article in resp.articles:
            articles.append(ArticleDocument(
                source_type=0 if information.source_type == "wechat" else 1,
                source_id=information.id,
                title=article.title,
                content=article.markdown_content,
                content_html=article.html_content,
                cover_image=article.icon,
                publish_time=datetime.fromisoformat(article.publish_date),
                source_url=article.original_url,
                create_time=datetime.fromisoformat(article.create_time),
                update_time=datetime.fromisoformat(article.update_time),
            ))
            doc_ids.append(article.id)
        article_service.bulk_index_articles_sync(articles, doc_ids)

        current += len(resp.articles)
        # get all articles
        if current >= resp.total or not resp.articles:
            break
        if not latest_create_time and current >= 36:
            break
        page += 1
    logger.debug(f"Finished syncing information for {information.id}. article nums: {current}")


def _update_channel_latest_article_update_time():
    """Update latest_article_update_time for all channels."""
    logger.debug("Starting to update latest_article_update_time for all channels.")
    with get_sync_db_session() as session:
        channels = session.exec(select(Channel)).all()
        updated_count = ChannelService.update_channels_latest_article_time_sync(list(channels))
        logger.debug(
            f"Finished updating latest_article_update_time for all channels. "
            f"updated_channel_count={updated_count}"
        )
