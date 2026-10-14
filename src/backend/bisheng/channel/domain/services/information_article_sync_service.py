import inspect
from collections.abc import Callable
from datetime import datetime
from time import time
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from bisheng.channel.domain.repositories.interfaces.information_article_sync_state_repository import (
    InformationArticleSyncStateRepository,
)
from bisheng.channel.domain.schemas.article_schema import ArticleDocument
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.common.services.metric_log import emit_metric
from bisheng.core.config.settings import IntelligenceCenterConf
from bisheng.core.external.bisheng_information_client.client import BishengInformationClient
from bisheng.core.external.bisheng_information_client.response_schema import (
    ArticleInfo,
    InformationSubscriptionItem,
)


class InformationArticleSyncService:
    def __init__(
        self,
        client: BishengInformationClient,
        state_repository: InformationArticleSyncStateRepository,
        article_service: ArticleEsService,
        *,
        get_conf: Callable[[], IntelligenceCenterConf] | None = None,
    ) -> None:
        self.client = client
        self.state_repository = state_repository
        self.article_service = article_service
        self._get_conf = get_conf

    def _conf(self) -> IntelligenceCenterConf:
        if self._get_conf is not None:
            return self._get_conf()
        conf = self.client.conf
        return conf if isinstance(conf, IntelligenceCenterConf) else IntelligenceCenterConf()

    async def sync_source(
        self,
        subscription: InformationSubscriptionItem,
        lock_guard: Any,
        dispatch_callback: Callable[[str, list[str], int], Any],
    ) -> dict:
        started_at = time()
        result = {"result": "failed", "new_article_ids": [], "written": 0}
        if not self._is_ready_today(subscription.last_sync_at):
            result["result"] = "not_ready"
            self._emit(subscription.id, result, started_at)
            return result

        state = await self.state_repository.find_by_source_id(subscription.id)
        if (
            state is not None
            and state.article_cursor_create_time is not None
            and (
                state.processed_remote_sync_at == subscription.last_sync_at
                and state.processed_article_list_updated_at == subscription.article_list_updated_at
            )
        ):
            result["result"] = "no_change"
            self._emit(subscription.id, result, started_at)
            return result

        if (
            state is not None
            and state.article_cursor_create_time is not None
            and subscription.article_list_updated_at is not None
            and state.processed_article_list_updated_at == subscription.article_list_updated_at
        ):
            if not lock_guard.refresh():
                result["result"] = "lock_lost"
                self._emit(subscription.id, result, started_at)
                return result
            committed = await self.state_repository.commit_if_unchanged(
                subscription.id,
                state,
                state.article_cursor_create_time,
                subscription.last_sync_at,
                subscription.article_list_updated_at,
            )
            result["result"] = "checked" if committed else "state_conflict"
            self._emit(subscription.id, result, started_at)
            return result

        try:
            if state is None:
                raise RuntimeError("information source metadata was not reconciled before article sync")
            if state.article_cursor_create_time is None:
                bootstrap = await self._bootstrap(
                    subscription,
                    lock_guard,
                    dispatch_callback,
                )
                if not lock_guard.refresh():
                    result["result"] = "lock_lost"
                    result["new_article_ids"] = bootstrap["new_ids"]
                    result["written"] = bootstrap["written"]
                    self._emit(subscription.id, result, started_at)
                    return result
                committed = await self.state_repository.commit_if_unchanged(
                    subscription.id,
                    state,
                    bootstrap["snapshot_max_create_time"],
                    subscription.last_sync_at,
                    subscription.article_list_updated_at,
                )
                result["result"] = "success" if committed else "state_conflict"
                result["new_article_ids"] = bootstrap["new_ids"]
                result["written"] = bootstrap["written"]
                self._emit(subscription.id, result, started_at)
                return result
            latest_subscription = subscription
            next_cursor = state.article_cursor_create_time
            all_new_ids: list[str] = []
            written = 0
            for attempt in range(2):
                scan = await self._scan_pages(
                    latest_subscription,
                    state.article_cursor_create_time,
                    lock_guard,
                    dispatch_callback,
                )
                next_cursor = max(next_cursor, scan["snapshot_max_create_time"])
                all_new_ids.extend(scan["new_ids"])
                written += scan["written"]
                reread = await self._reload_subscription(subscription.id)
                if reread is None:
                    raise RuntimeError("information subscription disappeared during article sync")
                if reread.article_list_updated_at == latest_subscription.article_list_updated_at:
                    latest_subscription = reread
                    break
                if attempt == 1:
                    result["result"] = "remote_changed"
                    result["new_article_ids"] = all_new_ids
                    result["written"] = written
                    self._emit(subscription.id, result, started_at)
                    return result
                latest_subscription = reread
            if not lock_guard.refresh():
                result["result"] = "lock_lost"
                result["new_article_ids"] = all_new_ids
                result["written"] = written
                self._emit(subscription.id, result, started_at)
                return result
            committed = await self.state_repository.commit_if_unchanged(
                subscription.id,
                state,
                next_cursor,
                latest_subscription.last_sync_at,
                latest_subscription.article_list_updated_at,
            )
            result["result"] = "success" if committed else "state_conflict"
            result["new_article_ids"] = all_new_ids
            result["written"] = written
        except Exception:
            logger.exception("information article sync failed source_id={}", subscription.id)
        self._emit(subscription.id, result, started_at)
        return result

    def _is_ready_today(self, last_sync_at: int | None) -> bool:
        if last_sync_at is None:
            return False
        timezone = ZoneInfo(self._conf().information_business_timezone)
        remote_day = datetime.fromtimestamp(last_sync_at, tz=timezone).date()
        return remote_day == datetime.now(tz=timezone).date()

    async def _bootstrap(
        self,
        subscription: InformationSubscriptionItem,
        lock_guard: Any,
        dispatch_callback: Callable[[str, list[str], int], Any],
    ) -> dict:
        conf = self._conf()
        page = await self.client.get_information_articles_bootstrap(
            subscription.id,
            limit=conf.information_initial_article_limit,
        )
        if (
            page.total < 0
            or page.total > conf.information_initial_article_limit
            or len(page.articles) != page.total
            or len({item.id for item in page.articles}) != len(page.articles)
            or page.snapshot_max_create_time is None
        ):
            raise RuntimeError("information bootstrap article response was incomplete")
        written = await self._write_articles(
            subscription,
            page.articles,
            lock_guard,
            dispatch_callback,
        )
        return {
            "snapshot_max_create_time": page.snapshot_max_create_time,
            "new_ids": written["new_ids"],
            "written": written["written"],
        }

    async def _scan_pages(
        self,
        subscription: InformationSubscriptionItem,
        boundary: int | None,
        lock_guard: Any,
        dispatch_callback: Callable[[str, list[str], int], Any],
    ) -> dict:
        page_number = 1
        expected_total: int | None = None
        seen_ids: set[str] = set()
        previous_sort_key: tuple[int, str] | None = None
        snapshot_max_create_time: int | None = None
        new_ids: list[str] = []
        written = 0
        while True:
            page = await self.client.get_information_articles_page(
                subscription.id,
                min_create_time=boundary,
                max_create_time=snapshot_max_create_time,
                page=page_number,
                page_size=100,
            )
            if page.current_page != page_number:
                raise RuntimeError("information article page number changed")
            if expected_total is None:
                expected_total = page.total
                snapshot_max_create_time = page.snapshot_max_create_time
                if snapshot_max_create_time is None:
                    raise RuntimeError("information article snapshot watermark is missing")
            elif page.total != expected_total:
                raise RuntimeError("information article totalCount changed")
            elif page.snapshot_max_create_time != snapshot_max_create_time:
                raise RuntimeError("information article snapshot watermark changed")
            page_articles: dict[str, ArticleDocument] = {}
            for article in page.articles:
                if article.id in seen_ids:
                    raise RuntimeError("information article response contains duplicate ids")
                create_time = self._timestamp(article.create_time)
                if boundary is not None and create_time < boundary:
                    raise RuntimeError("information article response crossed inclusive boundary")
                sort_key = (create_time, article.id)
                if previous_sort_key is not None and sort_key > previous_sort_key:
                    raise RuntimeError("information article response ordering is unstable")
                previous_sort_key = sort_key
                seen_ids.add(article.id)
                page_articles[article.id] = self._to_document(subscription, article)
            if page_articles:
                page_write = await self._write_documents(
                    subscription.id,
                    page_articles,
                    lock_guard,
                    dispatch_callback,
                )
                written += page_write["written"]
                new_ids.extend(page_write["new_ids"])
            if len(seen_ids) == expected_total:
                break
            if len(seen_ids) > expected_total or not page.articles:
                raise RuntimeError("information article snapshot ended before totalCount")
            page_number += 1
        return {
            "snapshot_max_create_time": snapshot_max_create_time,
            "new_ids": new_ids,
            "written": written,
        }

    async def _write_articles(
        self,
        subscription: InformationSubscriptionItem,
        articles: list[ArticleInfo],
        lock_guard: Any,
        dispatch_callback: Callable[[str, list[str], int], Any],
    ) -> dict:
        documents = {article.id: self._to_document(subscription, article) for article in articles}
        return await self._write_documents(
            subscription.id,
            documents,
            lock_guard,
            dispatch_callback,
        )

    async def _write_documents(
        self,
        source_id: str,
        documents: dict[str, ArticleDocument],
        lock_guard: Any,
        dispatch_callback: Callable[[str, list[str], int], Any],
    ) -> dict:
        if not documents:
            return {"new_ids": [], "written": 0}
        if not lock_guard.refresh():
            raise RuntimeError("information article lock ownership lost")
        existing = await self.article_service.mget_existing_ids(list(documents))
        bulk = await self.article_service.bulk_index_articles_detailed(documents)
        returned_ids = bulk.success_ids | set(bulk.failed_ids)
        known_success_ids = bulk.success_ids & set(documents)
        if known_success_ids:
            await self.article_service.refresh_index()
        deliverable = sorted(known_success_ids - existing)
        if deliverable:
            detected_at = int(time())
            try:
                dispatched = dispatch_callback(source_id, deliverable, detected_at)
                if inspect.isawaitable(dispatched):
                    await dispatched
            except Exception:
                logger.exception(
                    "information knowledge route dispatch failed source_id={} article_count={}",
                    source_id,
                    len(deliverable),
                )
                emit_metric(
                    "information_article_dispatch",
                    result="failed",
                    source_id=source_id,
                    article_count=len(deliverable),
                )
        if bulk.failed_ids or returned_ids != set(documents) or bulk.success_ids.intersection(bulk.failed_ids):
            raise RuntimeError("information article bulk result was incomplete")
        return {"new_ids": deliverable, "written": len(bulk.success_ids)}

    async def _reload_subscription(self, source_id: str) -> InformationSubscriptionItem | None:
        subscriptions = await self.client.list_all_subscriptions()
        return next((item for item in subscriptions if item.id == source_id), None)

    @classmethod
    def _to_document(
        cls,
        subscription: InformationSubscriptionItem,
        article: ArticleInfo,
    ) -> ArticleDocument:
        return ArticleDocument(
            source_type=0 if subscription.business_type == "wechat" else 1,
            source_id=subscription.id,
            title=article.title,
            content=article.markdown_content or "",
            content_html=article.html_content or "",
            cover_image=article.icon,
            publish_time=cls._datetime(article.publish_date),
            source_url=article.original_url,
            create_time=cls._datetime(article.create_time),
            update_time=cls._datetime(article.update_time),
        )

    @staticmethod
    def _timestamp(value: str | int | None) -> int:
        if value is None:
            raise RuntimeError("information article create_time is missing")
        if isinstance(value, int):
            return value
        if value.isdigit():
            return int(value)
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())

    @classmethod
    def _datetime(cls, value: str | int | None) -> datetime | None:
        if value is None:
            return None
        return datetime.fromtimestamp(cls._timestamp(value), tz=ZoneInfo("UTC"))

    @staticmethod
    def _emit(source_id: str, result: dict, started_at: float) -> None:
        emit_metric(
            "information_article_sync",
            result=result["result"],
            source_id=source_id,
            new_count=len(result["new_article_ids"]),
            written=result["written"],
            duration_ms=int((time() - started_at) * 1000),
        )
