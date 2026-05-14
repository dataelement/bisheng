from datetime import datetime
from typing import List

from loguru import logger
from sqlmodel import select, func

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
    logger.debug(f"Starting to sync information articles for {information_id}.")
    article_service = ArticleEsService()
    article_service.ensure_index_sync()
    need_update_informations = []
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
                    if (one.update_time.strftime("%Y-%m-%d") == datetime.now().strftime("%Y-%m-%d")
                    ) and (one.update_time.strftime("%Y-%m-%d %H:%M") != one.create_time.strftime("%Y-%m-%d %H:%M")):
                        logger.debug(
                            f"Skip information for {one.id} - {one.source_name}, because it has already been updated today.")
                        continue
                    _sync_one_information_article(one, article_service)
                    need_update_informations.append(one.id)
                    one.update_time = datetime.now()
                    channel_info_repository.update_sync(one)
                except Exception as e:
                    logger.exception(f"Failed to sync information article for source {one.id}: {e}")

            page += 1
    logger.debug("Finished syncing information articles")

    # Update latest_article_update_time for channels
    if need_update_informations:
        # Update only channels that use this information source
        logger.debug(f"Updating latest_article_update_time for channels using information_id={information_id}.")
        _update_channels_by_source_id(need_update_informations)


def _update_channels_by_source_id(source_ids: List[str]):
    """Update latest_article_update_time for channels that use the specified source_id."""
    with get_sync_db_session() as session:
        # Query channels whose source_list contains the source_id
        or_list = []
        for source_id in source_ids:
            or_list.append(func.json_contains(Channel.source_list, f'"{source_id}"'))
        channels = session.exec(select(Channel).where(*or_list)).all()

        if not channels:
            logger.debug(f"No channels found using source_ids={source_ids}.")
            return

        logger.debug(f"Found {len(channels)} channels using source_ids={source_ids}.")
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
        try:
            article_service.bulk_index_articles_sync(articles, doc_ids)
        except Exception as e:
            # if es timeout or over memory change to one by one
            for tmp_index, tmp_one in enumerate(articles):
                article_service.index_article(tmp_one, doc_ids[tmp_index])

        current += len(resp.articles)
        # get all articles
        if current >= resp.total or not resp.articles:
            logger.debug(f"sync all articles {information.id}.")
            break
        if not latest_create_time and current >= 36:
            logger.debug(f"sync more than 36 articles {information.id}.")
            break
        if latest_create_time and latest_create_time > articles[-1].create_time.timestamp():
            logger.debug(f"already get some articles {information.id}.")
            break
        page += 1
    logger.debug(f"Finished syncing information for {information.id}. article nums: {current}")
