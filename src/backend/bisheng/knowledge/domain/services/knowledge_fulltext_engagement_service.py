"""首钢门户互动统计投影、合并同步与历史校准。"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from loguru import logger

from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_engagement_repository_impl import (
    KnowledgeFulltextEngagementQueueRepositoryImpl,
    KnowledgeFulltextEngagementRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_index_repository_impl import (
    KnowledgeFulltextIndexRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_engagement_repository import (
    EngagementMetric,
    KnowledgeFulltextEngagementQueueRepository,
    KnowledgeFulltextEngagementRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_index_repository import (
    KnowledgeFulltextIndexRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextEngagementBulkResult,
)

SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")
_EVENT_METRICS: dict[str, EngagementMetric] = {
    "portal_document_read": "preview_count",
    "portal_document_download": "download_count",
}


async def settle_knowledge_fulltext_engagement_batch(
    *,
    queue_repository: KnowledgeFulltextEngagementQueueRepository,
    result: KnowledgeFulltextEngagementBulkResult,
    lease_owner: str,
    now_epoch: int,
) -> None:
    for file_id in result.updated_ids + result.noop_ids + result.missing_ids:
        await queue_repository.ack(file_id=file_id, lease_owner=lease_owner)
    for file_id in result.failed_ids:
        await queue_repository.retry(
            file_id=file_id,
            lease_owner=lease_owner,
            now_epoch=now_epoch,
        )


class KnowledgeFulltextEngagementService:
    def __init__(
        self,
        *,
        statistics_repository: KnowledgeFulltextEngagementRepository,
        queue_repository: KnowledgeFulltextEngagementQueueRepository,
        index_repository: KnowledgeFulltextIndexRepository,
        scheduler: Callable[[], Any] | None = None,
    ):
        self.statistics_repository = statistics_repository
        self.queue_repository = queue_repository
        self.index_repository = index_repository
        self.scheduler = scheduler

    async def project_event(
        self,
        *,
        event_type: str,
        source_app: str,
        status: str,
        file_id: int | str | None,
        occurred_at: datetime | None = None,
    ) -> bool:
        metric = _EVENT_METRICS.get(str(event_type))
        if metric is None or source_app != "shougang_portal" or status != "success":
            return False
        try:
            normalized_file_id = int(file_id or 0)
        except (TypeError, ValueError):
            return False
        if normalized_file_id <= 0:
            return False
        timestamp = occurred_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        local_date = timestamp.astimezone(SHANGHAI_TIMEZONE).date().isoformat()
        await self.statistics_repository.increment_daily(
            file_id=normalized_file_id,
            local_date=local_date,
            metric=metric,
            updated_at=timestamp,
        )
        await self.queue_repository.enqueue(
            file_id=normalized_file_id,
            now_epoch=int(timestamp.timestamp()),
        )
        if self.scheduler is not None and await self.queue_repository.acquire_schedule():
            scheduled = self.scheduler()
            if inspect.isawaitable(scheduled):
                await scheduled
        return True

    async def sync_file_ids(
        self,
        file_ids: list[int],
        *,
        updated_at: datetime,
    ) -> KnowledgeFulltextEngagementBulkResult:
        normalized = list(dict.fromkeys(int(item) for item in file_ids if int(item) > 0))
        totals = await self.statistics_repository.get_totals(normalized)
        return await self.index_repository.bulk_update_engagement(
            [totals[file_id] for file_id in normalized],
            updated_at=updated_at,
        )

    async def rebuild_history(self, *, now: datetime) -> dict[str, int]:
        summary = {
            "history_pages": 0,
            "daily_records": 0,
            "fulltext_pages": 0,
            "updated": 0,
            "noop": 0,
            "missing": 0,
            "failed": 0,
        }
        now_epoch = int(now.timestamp())
        for event_type, metric in _EVENT_METRICS.items():
            state = await self.queue_repository.load_history_cursor(event_type)
            if state and state.get("completed"):
                continue
            after_key = (state or {}).get("after_key")
            while True:
                page = await self.statistics_repository.aggregate_history_page(
                    event_type=event_type,
                    after_key=after_key,
                    page_size=constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_HISTORY_PAGE_SIZE,
                )
                summary["history_pages"] += 1
                changed_ids = await self.statistics_repository.set_daily_metric(
                    page.records,
                    metric=metric,
                    updated_at=now,
                )
                summary["daily_records"] += len(page.records)
                for file_id in changed_ids:
                    await self.queue_repository.enqueue(file_id=file_id, now_epoch=now_epoch)
                if page.after_key is None:
                    await self.queue_repository.save_history_cursor(event_type, {"completed": True})
                    break
                after_key = page.after_key
                await self.queue_repository.save_history_cursor(event_type, {"after_key": after_key})

        # 历史日统计 Bulk 使用 refresh=false；读取累计值前建立一次搜索可见性屏障，
        # 避免同一重建任务把刚写入的非零统计误读为 0。
        await self.statistics_repository.refresh_daily()

        fulltext_state = await self.queue_repository.load_history_cursor("fulltext")
        after_file_id = int((fulltext_state or {}).get("after_file_id") or 0) or None
        if not (fulltext_state and fulltext_state.get("completed")):
            while True:
                file_ids = await self.index_repository.list_file_ids(
                    after_file_id=after_file_id,
                    limit=constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_BATCH_SIZE,
                )
                if not file_ids:
                    await self.queue_repository.save_history_cursor("fulltext", {"completed": True})
                    break
                bulk_result = await self.sync_file_ids(file_ids, updated_at=now)
                summary["fulltext_pages"] += 1
                summary["updated"] += len(bulk_result.updated_ids)
                summary["noop"] += len(bulk_result.noop_ids)
                summary["missing"] += len(bulk_result.missing_ids)
                summary["failed"] += len(bulk_result.failed_ids)
                if bulk_result.failed_ids:
                    raise RuntimeError(f"failed to initialize {len(bulk_result.failed_ids)} engagement documents")
                after_file_id = file_ids[-1]
                await self.queue_repository.save_history_cursor(
                    "fulltext",
                    {"after_file_id": after_file_id},
                )
                if len(file_ids) < constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_BATCH_SIZE:
                    await self.queue_repository.save_history_cursor("fulltext", {"completed": True})
                    break
        return summary

    async def reconcile_recent(self, *, now: datetime) -> dict[str, int]:
        local_now = now.astimezone(SHANGHAI_TIMEZONE)
        first_day = local_now.date() - timedelta(days=constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_RECONCILE_DAYS - 1)
        start_at = datetime.combine(first_day, datetime.min.time(), tzinfo=SHANGHAI_TIMEZONE)
        end_at = datetime.combine(local_now.date() + timedelta(days=1), datetime.min.time(), tzinfo=SHANGHAI_TIMEZONE)
        changed: set[int] = set()
        observed: set[int] = set()
        page_count = 0
        record_count = 0
        for event_type, metric in _EVENT_METRICS.items():
            after_key = None
            while True:
                page = await self.statistics_repository.aggregate_history_page(
                    event_type=event_type,
                    after_key=after_key,
                    page_size=constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_HISTORY_PAGE_SIZE,
                    start_at=start_at,
                    end_at=end_at,
                )
                page_count += 1
                record_count += len(page.records)
                observed.update(record.file_id for record in page.records)
                changed.update(
                    await self.statistics_repository.set_daily_metric(
                        page.records,
                        metric=metric,
                        updated_at=now,
                    )
                )
                if page.after_key is None:
                    break
                after_key = page.after_key
        # 校准期间把原始埋点中出现过的文件全部重新入队。即使日统计绝对值未变化，
        # 也能恢复“日统计已成功、Redis 入队失败或 Redis 数据丢失”的窗口。
        for file_id in observed | changed:
            await self.queue_repository.enqueue(file_id=file_id, now_epoch=int(now.timestamp()))
        return {
            "pages": page_count,
            "records": record_count,
            "observed_file_count": len(observed),
            "changed_file_count": len(changed),
        }


async def project_knowledge_fulltext_engagement_best_effort(
    *,
    event_type: str,
    source_app: str,
    status: str,
    file_id: int | str | None,
    occurred_at: datetime | None = None,
) -> bool:
    """投影失败不得影响门户预览或下载主流程。"""
    try:
        from bisheng.common.services.config_service import settings
        from bisheng.core.search.elasticsearch.manager import get_es_connection, get_statistics_es_connection

        constants.ensure_runtime_compatible(multi_tenant_enabled=settings.multi_tenant.enabled)
        daily_client = await get_es_connection()
        raw_client = await get_statistics_es_connection()
        queue_repository = KnowledgeFulltextEngagementQueueRepositoryImpl()

        def schedule() -> None:
            from bisheng.worker.knowledge.fulltext_engagement import sync_knowledge_fulltext_engagement

            sync_knowledge_fulltext_engagement.apply_async(
                countdown=constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_DELAY_SECONDS,
                retry=False,
            )

        service = KnowledgeFulltextEngagementService(
            statistics_repository=KnowledgeFulltextEngagementRepositoryImpl(
                daily_client=daily_client,
                raw_client=raw_client,
            ),
            queue_repository=queue_repository,
            index_repository=KnowledgeFulltextIndexRepositoryImpl(daily_client),
            scheduler=schedule,
        )
        return await service.project_event(
            event_type=event_type,
            source_app=source_app,
            status=status,
            file_id=file_id,
            occurred_at=occurred_at,
        )
    except Exception:
        logger.bind(
            event_type=event_type,
            file_id=file_id,
            status="degraded",
            failure_stage="engagement_projection",
        ).exception("knowledge fulltext engagement projection failed")
        return False
