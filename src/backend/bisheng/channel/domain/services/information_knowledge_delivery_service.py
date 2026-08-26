import asyncio
import inspect
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import Any

from loguru import logger

from bisheng.channel.domain.repositories.interfaces.channel_knowledge_sync_repository import (
    ChannelKnowledgeSyncRepository,
)
from bisheng.channel.domain.repositories.interfaces.channel_repository import ChannelRepository
from bisheng.channel.domain.schemas.channel_manager_schema import AddArticlesToKnowledgeSpaceRequest
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.channel import ArticleSensitiveViolationError
from bisheng.common.errcode.knowledge_space import (
    SpaceFileNameDuplicateError,
    SpaceFolderNotFoundError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.common.services.metric_log import emit_metric
from bisheng.core.config.settings import IntelligenceCenterConf


class InformationKnowledgeDeliveryService:
    def __init__(
        self,
        channel_repository: ChannelRepository,
        config_repository: ChannelKnowledgeSyncRepository,
        article_service: ArticleEsService,
        *,
        channel_service: Any | None = None,
        get_conf: Callable[[], IntelligenceCenterConf] | None = None,
    ) -> None:
        self.channel_repository = channel_repository
        self.config_repository = config_repository
        self.article_service = article_service
        self.channel_service = channel_service
        self._get_conf = get_conf

    def _conf(self) -> IntelligenceCenterConf:
        if self._get_conf is not None:
            return self._get_conf()
        return IntelligenceCenterConf()

    async def route_current_tenant(
        self,
        source_id: str,
        article_ids: list[str],
        detected_at: int,
        dispatch_config: Callable[[str, list[str], int], Any],
    ) -> dict:
        result = {"result": "completed", "dispatched": 0, "skipped": 0, "failed": 0}
        if not self._conf().information_knowledge_delivery_enabled:
            result["result"] = "disabled"
            return result
        unique_article_ids = list(dict.fromkeys(article_ids))
        if not unique_article_ids:
            result["result"] = "empty"
            return result
        channels = await self.channel_repository.find_channels_referencing_source(source_id)
        channel_by_id = {str(channel.id): channel for channel in channels}
        configs = await self.config_repository.find_enabled_by_channel_ids(list(channel_by_id))
        for config in configs:
            try:
                channel = channel_by_id.get(str(config.channel_id))
                if channel is None or not config.is_enabled or not self._effective(config, detected_at):
                    result["skipped"] += 1
                    continue
                selected_ids = unique_article_ids
                if config.sub_channel_name:
                    group = self._find_filter_group(channel, config.sub_channel_name)
                    if group is None:
                        result["skipped"] += 1
                        continue
                    selected_ids = await asyncio.to_thread(
                        self.article_service.match_article_ids_sync,
                        unique_article_ids,
                        list(dict.fromkeys(str(item) for item in (channel.source_list or []))),
                        [group],
                    )
                if not selected_ids:
                    result["skipped"] += 1
                    continue
                dispatched = dispatch_config(config.id, list(selected_ids), detected_at)
                if inspect.isawaitable(dispatched):
                    await dispatched
                result["dispatched"] += 1
            except Exception:
                result["failed"] += 1
                logger.exception(
                    "information knowledge routing failed source_id={} config_id={}",
                    source_id,
                    getattr(config, "id", "unknown"),
                )
        emit_metric(
            "information_knowledge_routing",
            result=result["result"],
            source_id=source_id,
            dispatched=result["dispatched"],
            skipped=result["skipped"],
            failed=result["failed"],
        )
        return result

    async def deliver_to_config(
        self,
        tenant_id: int,
        sync_config_id: str,
        article_ids: list[str],
        detected_at: int,
    ) -> dict:
        result: dict[str, Any] = {"result": "completed", "accepted": 0, "failed": {}}
        config = await self.config_repository.find_by_id(sync_config_id)
        if config is None:
            result["result"] = "config_missing"
            return result
        channel = await self.channel_repository.find_by_id(config.channel_id)
        if channel is None:
            result["result"] = "channel_missing"
            return result
        if not config.is_enabled:
            result["result"] = "config_disabled"
            return result
        if not self._effective(config, detected_at):
            result["result"] = "config_not_effective"
            return result
        if self.channel_service is None:
            raise RuntimeError("channel_service is required for knowledge delivery")
        failed = Counter()
        login_user = UserPayload(
            user_id=int(config.user_id),
            tenant_id=tenant_id,
            user_name="information-worker",
            user_role=[],
        )
        for article_id in dict.fromkeys(article_ids):
            request = AddArticlesToKnowledgeSpaceRequest(
                knowledge_id=int(config.knowledge_space_id),
                article_ids=[article_id],
                parent_id=(int(config.folder_id) if config.folder_id and str(config.folder_id).isdigit() else None),
                skip_missing_and_duplicates=False,
            )
            try:
                await self.channel_service.add_articles_to_knowledge_space(request, login_user, request=None)
                result["accepted"] += 1
            except Exception as exc:
                category = self._classify_failure(exc)
                failed[category] += 1
                logger.exception(
                    "information knowledge delivery failed tenant_id={} config_id={} article_id={} category={}",
                    tenant_id,
                    sync_config_id,
                    article_id,
                    category,
                )
        result["failed"] = dict(failed)
        emit_metric(
            "information_knowledge_delivery",
            result=result["result"],
            tenant_id=tenant_id,
            config_id=sync_config_id,
            accepted=result["accepted"],
            failed=sum(failed.values()),
            failed_categories=dict(failed),
        )
        return result

    @staticmethod
    def _find_filter_group(channel: Any, sub_channel_name: str) -> dict | None:
        for group in channel.filter_rules or []:
            if isinstance(group, dict) and group.get("channel_type") == "sub" and group.get("name") == sub_channel_name:
                return group
        return None

    @staticmethod
    def _effective(config: Any, detected_at: int) -> bool:
        effective_at = max(
            InformationKnowledgeDeliveryService._to_timestamp(config.create_time),
            InformationKnowledgeDeliveryService._to_timestamp(config.update_time),
        )
        return effective_at <= detected_at

    @staticmethod
    def _to_timestamp(value: datetime | int) -> int:
        return int(value.timestamp()) if isinstance(value, datetime) else int(value)

    @staticmethod
    def _classify_failure(exc: Exception) -> str:
        if isinstance(exc, SpaceFileNameDuplicateError):
            return "duplicate_name"
        if isinstance(exc, (SpaceNotFoundError, SpaceFolderNotFoundError)):
            return "target_missing"
        if isinstance(exc, SpacePermissionDeniedError):
            return "permission"
        if isinstance(exc, ArticleSensitiveViolationError):
            return "sensitive"
        if isinstance(exc, ValueError) and "Article not found" in str(exc):
            return "article_missing"
        name = type(exc).__name__.lower()
        if "quota" in name or "limit" in name or "exceeded" in name:
            return "quota"
        if "permission" in name or "forbidden" in name or "access" in name:
            return "permission"
        if "notfound" in name or "not_found" in name:
            return "target_missing"
        return "system_failed"
