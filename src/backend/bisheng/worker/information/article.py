import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from loguru import logger
from sqlmodel import select, func

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
from bisheng.channel.domain.models.channel_knowledge_sync import (
    ChannelKnowledgeSync,
    ChannelKnowledgeSyncDao,
)
from bisheng.channel.domain.repositories.implementations.channel_info_source_repository_impl import \
    ChannelInfoSourceRepositoryImpl
from bisheng.channel.domain.schemas.article_schema import ArticleDocument
from bisheng.channel.domain.schemas.channel_manager_schema import (
    AddArticlesToKnowledgeSpaceRequest,
)
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
    # v2.5 Module D: record article ids indexed during THIS worker run so the
    # knowledge-space sync hook below can push just the fresh ones.
    indexed_by_source: Dict[str, List[str]] = {}
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
                    need_update_informations.append(one.id)

                    new_ids = _sync_one_information_article(one, article_service)
                    if new_ids:
                        indexed_by_source.setdefault(str(one.id), []).extend(new_ids)
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
    all_new_ids: List[str] = []
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
        all_new_ids.extend(doc_ids)

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
    return all_new_ids


# --------------------------------------------------------------------------- #
# v2.5 Module D — Channel ➜ Knowledge Space sync hook.
# For each channel that has enabled ChannelKnowledgeSync rows, push the
# articles indexed this worker run into each configured knowledge space.
# Sub-channel bindings are resolved against the channel's `filter_rules` JSON:
# for a sub-channel binding we take the group where `channel_type == "sub"`
# and `name == sub_channel_name` and use it to filter fresh article ids
# via ArticleEsService.match_article_ids_sync.
# --------------------------------------------------------------------------- #


def _find_sub_channel_filter_group(
    channel: Channel, sub_channel_name: str,
) -> Optional[Dict]:
    """Return the ChannelFilterRules group for a sub-channel, or None."""
    for g in (channel.filter_rules or []):
        if not isinstance(g, dict):
            continue
        if g.get("channel_type") == "sub" and g.get("name") == sub_channel_name:
            return g
    return None


def _resolve_article_ids_for_config(
    config: ChannelKnowledgeSync,
    channel: Channel,
    indexed_by_source: Dict[str, List[str]],
    article_service: ArticleEsService,
) -> List[str]:
    """Compute the article ids this config should receive this run."""
    channel_sources = [str(s) for s in (channel.source_list or [])]
    new_ids: List[str] = []
    for sid in channel_sources:
        new_ids.extend(indexed_by_source.get(sid, []))
    if not new_ids:
        return []

    if not config.sub_channel_name:
        return new_ids

    group = _find_sub_channel_filter_group(channel, config.sub_channel_name)
    if not group:
        # No filter group means the sub-channel no longer exists — skip to avoid
        # silently pushing the main channel's articles into a stale binding.
        logger.warning(
            f"Sync config {config.id}: sub-channel {config.sub_channel_name!r} "
            f"has no filter rules on channel {channel.id}; skipping."
        )
        return []
    try:
        return article_service.match_article_ids_sync(
            article_ids=new_ids,
            source_ids=channel_sources or None,
            filter_rules=[group],
        )
    except Exception as exc:
        logger.exception(
            f"Filter evaluation failed for config {config.id}: {exc}"
        )
        return []


def _sync_new_articles_to_knowledge_spaces(
    indexed_by_source: Dict[str, List[str]],
    information_id: str = None,
    article_service: Optional[ArticleEsService] = None,
) -> None:
    if not indexed_by_source:
        logger.debug("No freshly-indexed articles; skipping knowledge-space sync hook.")
        return

    article_service = article_service or ArticleEsService()

    with get_sync_db_session() as session:
        if information_id:
            channels = session.exec(
                select(Channel).where(
                    func.json_contains(Channel.source_list, f'"{information_id}"')
                )
            ).all()
        else:
            channels = session.exec(select(Channel)).all()

    if not channels:
        return

    channel_ids = [c.id for c in channels]
    sync_configs = ChannelKnowledgeSyncDao.list_by_channel_ids_enabled(channel_ids)
    if not sync_configs:
        logger.debug("No enabled knowledge-sync configs for affected channels.")
        return

    channel_by_id = {c.id: c for c in channels}
    logger.info(
        f"Knowledge-space sync hook: {len(sync_configs)} enabled configs "
        f"across {len(channel_ids)} channels."
    )

    # Build a list of dispatch tasks, skipping configs that have nothing to send.
    pending: List[Tuple[ChannelKnowledgeSync, AddArticlesToKnowledgeSpaceRequest]] = []
    for config in sync_configs:
        try:
            channel = channel_by_id.get(config.channel_id)
            if not channel:
                continue

            article_ids = _resolve_article_ids_for_config(
                config, channel, indexed_by_source, article_service,
            )
            if not article_ids:
                continue

            try:
                kid = int(config.knowledge_space_id)
            except (TypeError, ValueError):
                logger.warning(
                    f"Config {config.id}: non-int knowledge_space_id "
                    f"{config.knowledge_space_id!r}, skipping."
                )
                continue

            req = AddArticlesToKnowledgeSpaceRequest(
                knowledge_id=kid,
                article_ids=article_ids,
                parent_id=(
                    int(config.folder_id)
                    if config.folder_id and str(config.folder_id).isdigit()
                    else None
                ),
                # Background sync is best-effort: missing ES docs and duplicate
                # file names in the target space must not abort the batch.
                skip_missing_and_duplicates=True,
            )
            pending.append((config, req))
        except Exception as exc:
            logger.exception(
                f"Failed to prepare sync for config {config.id} "
                f"(channel {config.channel_id}): {exc}"
            )

    if not pending:
        return

    # Force an ES refresh so freshly-bulk-indexed docs are visible to the
    # GET-by-id lookups inside add_articles_to_knowledge_space. Without this
    # the first config(s) can race the indexer and fail with "Article not found".
    article_service.refresh_index_sync()

    # Dispatch all pending configs on a single event loop.
    asyncio.run(_dispatch_all(pending))


async def _dispatch_all(
    pending: List[Tuple[ChannelKnowledgeSync, AddArticlesToKnowledgeSpaceRequest]],
) -> None:
    async def _one(config: ChannelKnowledgeSync, req: AddArticlesToKnowledgeSpaceRequest):
        try:
            await _async_add_articles_to_knowledge(req, int(config.user_id))
            ChannelKnowledgeSyncDao.touch_update_time(config.id)
            logger.info(
                f"Synced {len(req.article_ids)} articles from channel "
                f"{config.channel_id} → knowledge_space {config.knowledge_space_id} "
                f"(config {config.id})"
            )
        except Exception as exc:
            logger.exception(
                f"Failed to sync config {config.id} "
                f"(channel {config.channel_id}): {exc}"
            )

    await asyncio.gather(*(_one(c, r) for c, r in pending), return_exceptions=True)


async def _async_add_articles_to_knowledge(
    req: AddArticlesToKnowledgeSpaceRequest, user_id: int,
):
    """Run add_articles_to_knowledge_space in an async context.

    Instantiates a ChannelService with the same repositories used by the REST
    endpoint so permission checks + storage flows stay identical.
    """
    from bisheng.channel.api.dependencies import get_article_es_service
    from bisheng.channel.domain.repositories.implementations.article_read_repository_impl import (
        ArticleReadRepositoryImpl,
    )
    from bisheng.channel.domain.repositories.implementations.channel_info_source_repository_impl import (
        ChannelInfoSourceRepositoryImpl,
    )
    from bisheng.channel.domain.repositories.implementations.channel_repository_impl import (
        ChannelRepositoryImpl,
    )
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.repositories.implementations.space_channel_member_repository_impl import (
        SpaceChannelMemberRepositoryImpl,
    )
    from bisheng.core.database import get_async_db_session
    from bisheng.message.api.dependencies import get_message_service as _get_message_service

    async with get_async_db_session() as session:
        svc = ChannelService(
            channel_repository=ChannelRepositoryImpl(session),
            space_channel_member_repository=SpaceChannelMemberRepositoryImpl(session),
            channel_info_source_repository=ChannelInfoSourceRepositoryImpl(session),
            article_es_service=get_article_es_service(),
            article_read_repository=ArticleReadRepositoryImpl(session),
            message_service=await _get_message_service(session),
        )
        login_user = UserPayload(user_id=user_id, user_name="system-worker", role="user")
        await svc.add_articles_to_knowledge_space(req, login_user, request=None)
