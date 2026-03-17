from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlmodel import select

from bisheng.channel.domain.es.article_index import ARTICLE_INDEX_NAME
from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
from bisheng.channel.domain.repositories.implementations.channel_info_source_repository_impl import \
    ChannelInfoSourceRepositoryImpl
from bisheng.channel.domain.schemas.article_schema import ArticleDocument
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.core.database import get_sync_db_session
from bisheng.core.external.bisheng_information_client.bisheng_information_manager import \
    get_bisheng_information_client_sync
from bisheng.core.logger import trace_id_var
from bisheng.core.search.elasticsearch.manager import get_es_connection_sync
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

    # Update latest_article_update_time for all channels that use this information source
    if information_id is None:
        logger.debug("Updating latest_article_update_time for all channels.")
        _update_channel_latest_article_update_time()


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
    logger.debug("Starting to update latest_article_update_time for all channels.")
    article_service = ArticleEsService()
    updated_channel_count = 0

    with get_sync_db_session() as session:
        channels = session.exec(select(Channel)).all()

        for channel in channels:
            try:
                latest_article_create_time = _get_channel_latest_article_create_time(
                    channel=channel,
                    article_service=article_service,
                )
            except Exception as exc:
                logger.exception(
                    f"Failed to query latest article create_time for channel {channel.id}: {exc}"
                )
                continue

            if latest_article_create_time is None:
                continue

            current_latest_time = _normalize_datetime(channel.latest_article_update_time)
            if current_latest_time is None or latest_article_create_time > current_latest_time:
                channel.latest_article_update_time = latest_article_create_time
                session.add(channel)
                updated_channel_count += 1

        if updated_channel_count > 0:
            session.commit()

    logger.debug(
        f"Finished updating latest_article_update_time for all channels. "
        f"updated_channel_count={updated_channel_count}"
    )


def _get_channel_latest_article_create_time(
        channel: Channel,
        article_service: ArticleEsService,
) -> Optional[datetime]:
    """Get the latest article create_time for a channel under main filter rules."""
    query = article_service._build_count_query(
        source_ids=channel.source_list or [],
        filter_rules=_extract_main_filter_rules(channel) or None,
    )
    if query is None:
        return None

    client = get_es_connection_sync()
    body = {
        "size": 1,
        "query": query,
        "sort": [{"create_time": {"order": "desc"}}],
        "_source": ["create_time"],
    }
    response = client.search(index=ARTICLE_INDEX_NAME, body=body)
    hits = response["hits"]["hits"]
    if not hits:
        return None

    latest_create_time = hits[0]["_source"].get("create_time")
    if not latest_create_time:
        return None

    return _normalize_datetime(datetime.fromisoformat(latest_create_time))


def _extract_main_filter_rules(channel: Channel) -> List[Dict[str, Any]]:
    """Extract main channel filter rules from channel configuration."""
    filter_rules_raw = channel.filter_rules or []
    main_rules: List[Dict[str, Any]] = []

    for filter_rule in filter_rules_raw:
        channel_type = filter_rule.get("channel_type", "main")
        if channel_type == "main":
            main_rules.extend(filter_rule.get("rules", []))

    return main_rules


def _normalize_datetime(value: Optional[datetime]) -> Optional[datetime]:
    """Normalize datetime values before comparison and persistence."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value
