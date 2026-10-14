import asyncio

from loguru import logger
from sqlmodel import select

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.models.channel_knowledge_sync import (
    ChannelKnowledgeSync,
    ChannelKnowledgeSyncDao,
)
from bisheng.channel.domain.repositories.implementations.channel_info_source_repository_impl import (
    ChannelInfoSourceRepositoryImpl,
)
from bisheng.channel.domain.repositories.implementations.information_article_sync_state_repository_impl import (
    InformationArticleSyncStateRepositoryImpl,
)
from bisheng.channel.domain.schemas.channel_manager_schema import (
    AddArticlesToKnowledgeSpaceRequest,
)
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.channel.domain.services.information_article_sync_service import InformationArticleSyncService
from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.core.database.dialect_helpers import json_array_contains
from bisheng.core.external.bisheng_information_client.bisheng_information_manager import (
    get_bisheng_information_client,
)
from bisheng.core.logger import trace_id_var
from bisheng.utils import generate_uuid
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.information.redis_lock import InformationRedisLock
from bisheng.worker.main import bisheng_celery


def _db_dialect() -> str:
    try:
        from bisheng.core.database.manager import sync_get_database_connection

        return sync_get_database_connection().engine.dialect.name
    except Exception:
        return "mysql"


@bisheng_celery.task
def sync_information_article(information_id: str | None = None):
    trace_id_var.set(f"sync_all_information_articles_{generate_uuid()}")
    # Celery Beat fires this once with no request/tenant context. The
    # information-source tables are tenant-aware, so iterate every active tenant
    # and run the sync under that tenant's context (mirrors reconcile_all_tenants);
    # otherwise the first SELECT on channel_info_source raises NoTenantContextError
    # and nothing ever syncs on a multi-tenant deploy.
    for tenant_id in _active_tenant_ids_sync():
        token = set_current_tenant_id(tenant_id)
        try:
            _sync_information_article_for_tenant(information_id)
        except Exception:
            # Isolate per-tenant failures so one bad tenant never blocks the rest.
            logger.exception(f"sync_information_article failed for tenant={tenant_id}")
        finally:
            current_tenant_id.reset(token)


def _active_tenant_ids_sync() -> list[int]:
    """Active tenant ids to sync — sync counterpart of reconcile._active_tenant_ids.

    Single-tenant deployments behave as tenant_id=1.
    """
    from bisheng.common.services.config_service import settings

    if not settings.multi_tenant.enabled:
        return [DEFAULT_TENANT_ID]

    from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao

    child_ids = TenantDao.get_children_ids_active()
    return [ROOT_TENANT_ID, *child_ids]


def _sync_information_article_for_tenant(information_id: str | None = None):
    article_service = ArticleEsService()
    indexed_by_source, updated_sources = run_async_task(
        lambda: _sync_tenant_sources_async(information_id, article_service)
    )
    for source_id in updated_sources:
        _update_channels_by_source_id([source_id])
    _sync_new_articles_to_knowledge_spaces(
        indexed_by_source,
        information_id=information_id,
        article_service=article_service,
    )


def _new_source_lock(source_id: str) -> InformationRedisLock:
    from bisheng.core.cache.redis_manager import get_redis_client_sync

    return InformationRedisLock(
        get_redis_client_sync().connection,
        f"information:article-sync:{source_id}",
        ttl_seconds=7200,
    )


async def _sync_tenant_sources_async(
    information_id: str | None,
    article_service: ArticleEsService,
) -> tuple[dict[str, list[str]], list[str]]:
    client = await get_bisheng_information_client()
    # A failed or incomplete snapshot must not mark any local source as processed.
    subscriptions = {item.id: item for item in await client.list_all_subscriptions()}
    async with get_async_db_session() as session:
        repository = ChannelInfoSourceRepositoryImpl(session)
        sources = await repository.find_by_ids([information_id]) if information_id else await repository.find_all()
    indexed_by_source: dict[str, list[str]] = {}
    updated_sources: list[str] = []

    def dispatch(source_id: str, article_ids: list[str], detected_at: int) -> None:
        # Keep the target branch's existing knowledge-space delivery hook.
        indexed_by_source.setdefault(source_id, []).extend(article_ids)

    for source in sources:
        subscription = subscriptions.get(source.id)
        if subscription is None:
            logger.warning("information article source is not subscribed source_id={}", source.id)
            continue
        lock = _new_source_lock(source.id)
        if not lock.acquire():
            logger.warning(
                "information article source skipped source_id={} redis_available={}",
                source.id,
                lock.redis_available,
            )
            continue
        try:
            async with get_async_db_session() as session:
                service = InformationArticleSyncService(
                    client,
                    InformationArticleSyncStateRepositoryImpl(session),
                    article_service,
                )
                result = await service.sync_source(subscription, lock, dispatch)
            if result["written"] or indexed_by_source.get(source.id):
                updated_sources.append(source.id)
        except Exception:
            logger.exception("information article worker source failed source_id={}", source.id)
        finally:
            lock.release()
    return indexed_by_source, updated_sources


def _update_channels_by_source_id(source_ids: list[str]):
    """Update latest_article_update_time for channels that use the specified source_id."""
    with get_sync_db_session() as session:
        dialect = session.bind.dialect.name if session.bind else _db_dialect()
        or_list = []
        for source_id in source_ids:
            or_list.append(json_array_contains(Channel.source_list, f'"{source_id}"', dialect))
        channels = session.exec(select(Channel).where(*or_list)).all()

        if not channels:
            logger.debug(f"No channels found using source_ids={source_ids}.")
            return

        logger.debug(f"Found {len(channels)} channels using source_ids={source_ids}.")
        updated_count = ChannelService.update_channels_latest_article_time_sync(list(channels))
        logger.debug(f"Updated latest_article_update_time for {updated_count} channels.")


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
    channel: Channel,
    sub_channel_name: str,
) -> dict | None:
    """Return the ChannelFilterRules group for a sub-channel, or None."""
    for g in channel.filter_rules or []:
        if not isinstance(g, dict):
            continue
        if g.get("channel_type") == "sub" and g.get("name") == sub_channel_name:
            return g
    return None


def _resolve_article_ids_for_config(
    config: ChannelKnowledgeSync,
    channel: Channel,
    indexed_by_source: dict[str, list[str]],
    article_service: ArticleEsService,
) -> list[str]:
    """Compute the article ids this config should receive this run."""
    channel_sources = [str(s) for s in (channel.source_list or [])]
    new_ids: list[str] = []
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
        logger.exception(f"Filter evaluation failed for config {config.id}: {exc}")
        return []


def _drop_dead_target_configs(
    configs: list[ChannelKnowledgeSync],
) -> list[ChannelKnowledgeSync]:
    """Filter out configs whose knowledge_space or folder has been deleted."""
    space_ids = {
        int(c.knowledge_space_id) for c in configs if c.knowledge_space_id and str(c.knowledge_space_id).isdigit()
    }
    folder_ids = {int(c.folder_id) for c in configs if c.folder_id and str(c.folder_id).isdigit()}
    if not space_ids and not folder_ids:
        return list(configs)

    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

    existing_spaces = set()
    existing_folders = set()
    with get_sync_db_session() as session:
        if space_ids:
            for row in session.exec(select(Knowledge.id).where(Knowledge.id.in_(space_ids))).all():
                kid = row[0] if isinstance(row, tuple) else row
                existing_spaces.add(int(kid))
        if folder_ids:
            for row in session.exec(select(KnowledgeFile.id).where(KnowledgeFile.id.in_(folder_ids))).all():
                fid = row[0] if isinstance(row, tuple) else row
                existing_folders.add(int(fid))

    survivors: list[ChannelKnowledgeSync] = []
    for c in configs:
        sid = c.knowledge_space_id
        if sid and str(sid).isdigit() and int(sid) not in existing_spaces:
            logger.warning(f"Sync config {c.id}: knowledge_space {sid} no longer exists; skipping.")
            continue
        fid_val = c.folder_id
        if fid_val and str(fid_val).isdigit() and int(fid_val) not in existing_folders:
            logger.warning(f"Sync config {c.id}: folder {fid_val} no longer exists; skipping.")
            continue
        survivors.append(c)
    return survivors


def _sync_new_articles_to_knowledge_spaces(
    indexed_by_source: dict[str, list[str]],
    information_id: str | None = None,
    article_service: ArticleEsService | None = None,
) -> None:
    if not indexed_by_source:
        logger.debug("No freshly-indexed articles; skipping knowledge-space sync hook.")
        return

    article_service = article_service or ArticleEsService()

    with get_sync_db_session() as session:
        if information_id:
            dialect = session.bind.dialect.name if session.bind else _db_dialect()
            channels = session.exec(
                select(Channel).where(json_array_contains(Channel.source_list, f'"{information_id}"', dialect))
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

    # Defensive: drop configs whose target space or folder no longer exists.
    # delete_space/delete_folder cleanup hooks may have failed or pre-date this
    # row; without this guard the worker writes MinIO garbage and logs an
    # exception every run for each orphan binding.
    sync_configs = _drop_dead_target_configs(sync_configs)
    if not sync_configs:
        logger.info("All sync configs reference deleted spaces/folders; skipping.")
        return

    channel_by_id = {c.id: c for c in channels}
    logger.info(f"Knowledge-space sync hook: {len(sync_configs)} enabled configs across {len(channel_ids)} channels.")

    # Build a list of dispatch tasks, skipping configs that have nothing to send.
    pending: list[tuple[ChannelKnowledgeSync, AddArticlesToKnowledgeSpaceRequest]] = []
    for config in sync_configs:
        try:
            channel = channel_by_id.get(config.channel_id)
            if not channel:
                continue

            article_ids = _resolve_article_ids_for_config(
                config,
                channel,
                indexed_by_source,
                article_service,
            )
            if not article_ids:
                continue

            try:
                kid = int(config.knowledge_space_id)
            except (TypeError, ValueError):
                logger.warning(
                    f"Config {config.id}: non-int knowledge_space_id {config.knowledge_space_id!r}, skipping."
                )
                continue

            req = AddArticlesToKnowledgeSpaceRequest(
                knowledge_id=kid,
                article_ids=article_ids,
                parent_id=(int(config.folder_id) if config.folder_id and str(config.folder_id).isdigit() else None),
                # Background sync is best-effort: missing ES docs and duplicate
                # file names in the target space must not abort the batch.
                skip_missing_and_duplicates=True,
            )
            pending.append((config, req))
        except Exception as exc:
            logger.exception(f"Failed to prepare sync for config {config.id} (channel {config.channel_id}): {exc}")

    if not pending:
        return

    # Force an ES refresh so freshly-bulk-indexed docs are visible to the
    # GET-by-id lookups inside add_articles_to_knowledge_space. Without this
    # the first config(s) can race the indexer and fail with "Article not found".
    article_service.refresh_index_sync()

    # Dispatch all pending configs on a single event loop.
    run_async_task(lambda: _dispatch_all(pending))


async def _dispatch_all(
    pending: list[tuple[ChannelKnowledgeSync, AddArticlesToKnowledgeSpaceRequest]],
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
            logger.exception(f"Failed to sync config {config.id} (channel {config.channel_id}): {exc}")

    await asyncio.gather(*(_one(c, r) for c, r in pending), return_exceptions=True)


async def _async_add_articles_to_knowledge(
    req: AddArticlesToKnowledgeSpaceRequest,
    user_id: int,
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
