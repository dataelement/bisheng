"""Orchestrates the daily portal hot-search rebuild (F048).

Flow (see spec §9): acquire lock -> Pass1 candidates -> Pass2 records ->
clean+dedup -> LLM intent grouping -> heat scoring + thresholds -> rewrite
Top-K -> transactional persist (snapshot + batch_run + candidate) -> purge ->
Redis replace -> release lock. Any failure records a failed batch_run and
leaves the previous snapshot intact.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

from loguru import logger

from bisheng.knowledge.domain.repositories.interfaces.portal_hot_search_redis_repository import (
    PortalHotSearchRedisRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.portal_hot_search_repository import (
    PortalHotSearchRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.portal_hot_search_telemetry_repository import (
    PortalHotSearchTelemetryRepository,
)
from bisheng.knowledge.domain.schemas.portal_hot_search_schema import (
    HotSearchBatchStats,
    PortalHotSearchItem,
)
from bisheng.knowledge.domain.services.portal_hot_search_filter_service import (
    PortalHotSearchFilterService,
)
from bisheng.knowledge.domain.services.portal_hot_search_intent_service import (
    PortalHotSearchIntentService,
)
from bisheng.knowledge.domain.services.portal_hot_search_rewrite_service import (
    PortalHotSearchRewriteService,
)
from bisheng.knowledge.domain.services.portal_hot_search_scoring_service import (
    PortalHotSearchScoringService,
)


class PortalHotSearchPipelineService:
    def __init__(
        self,
        *,
        tenant_id: int,
        config,
        telemetry_repository: PortalHotSearchTelemetryRepository,
        hot_search_repository: PortalHotSearchRepository,
        redis_repository: PortalHotSearchRedisRepository,
        filter_service: PortalHotSearchFilterService,
        intent_service: PortalHotSearchIntentService,
        scoring_service: PortalHotSearchScoringService,
        rewrite_service: PortalHotSearchRewriteService,
    ) -> None:
        self.tenant_id = int(tenant_id)
        self.config = config
        self.telemetry_repository = telemetry_repository
        self.hot_search_repository = hot_search_repository
        self.redis_repository = redis_repository
        self.filter_service = filter_service
        self.intent_service = intent_service
        self.scoring_service = scoring_service
        self.rewrite_service = rewrite_service

    def _build_batch_id(self, now: datetime) -> str:
        local = now.astimezone(timezone.utc)
        return f"{local:%Y%m%d}-{local:%H%M%S}"

    async def run(self, *, now: datetime | None = None) -> HotSearchBatchStats:
        now = now or datetime.now(timezone.utc)
        if not await self.redis_repository.acquire_lock(self.tenant_id):
            logger.info("hot-search rebuild skipped, lock held tenant={}", self.tenant_id)
            return HotSearchBatchStats(batch_id="", status="skipped")

        started = time.monotonic()
        batch_id = self._build_batch_id(now)
        window_end = now
        window_start = now - timedelta(days=self.config.window_days)
        stats = HotSearchBatchStats(batch_id=batch_id, status="running")
        try:
            await self.hot_search_repository.insert_batch_run(
                stats, window_start=window_start, window_end=window_end, computed_at=now
            )

            agg = await self.telemetry_repository.aggregate_candidate_queries(
                self.tenant_id,
                window_start,
                window_end,
                page_size=self.config.page_size,
                max_pages=self.config.max_pages,
                candidate_top_n=self.config.candidate_top_n,
            )
            candidate_norm_queries = [s.normalized_query for s in agg.stats]
            stats.candidate_count = len(candidate_norm_queries)
            stats.scanned_count = sum(s.doc_count for s in agg.stats)
            stats.es_pages = agg.es_pages

            records_result = await self.telemetry_repository.list_candidate_search_records(
                self.tenant_id,
                candidate_norm_queries,
                window_start,
                window_end,
                page_size=self.config.page_size,
                max_pages=self.config.max_pages,
                per_query_scan_cap=self.config.per_query_scan_cap,
            )
            stats.es_pages += records_result.es_pages

            cleaned = self.filter_service.filter_and_dedup(records_result.records)
            stats.dedup_record_count = len(cleaned)
            distinct_cleaned = list(dict.fromkeys(r.cleaned_query for r in cleaned))
            stats.distinct_query_count = len(distinct_cleaned)

            intent_result = self.intent_service.group(distinct_cleaned[: self.config.candidate_top_n])
            stats.llm_degraded = intent_result.degraded
            stats.llm_group_calls = 0 if intent_result.degraded else 1

            ranked = self.scoring_service.score(intent_result.groups, cleaned, now=now, top_k=self.config.top_k)
            stats.qualified_count = sum(1 for item in ranked if item.qualified)

            llm_samples: dict[str, str] = {}
            rewrite_calls = 0
            for item in ranked:
                if item.final_rank is None:
                    continue
                display, source = self.rewrite_service.rewrite(item.canonical_query)
                item.display_query = display
                item.rewrite_source = source
                if source != "passthrough":
                    rewrite_calls += 1
                sample = json.dumps(
                    {"canonical": item.canonical_query, "display": display, "source": source},
                    ensure_ascii=False,
                )
                llm_samples[item.intent_key] = sample[: self.config.llm_sample_max_chars]
            stats.llm_rewrite_calls = rewrite_calls

            stats.truncated = bool(agg.truncated or records_result.truncated)
            stats.status = "degraded" if stats.truncated else "success"

            published = [
                PortalHotSearchItem(rank=item.final_rank, query=item.display_query)
                for item in ranked
                if item.final_rank is not None
            ]

            diagnostic_top = ranked[: self.config.diagnostic_candidate_top_n]
            if published:
                await self.hot_search_repository.replace_snapshot(ranked, batch_id=batch_id, computed_at=now)
                await self.redis_repository.replace(self.tenant_id, published)
            else:
                logger.info(
                    "hot-search rebuild produced no qualified results; keeping previous snapshot tenant={}",
                    self.tenant_id,
                )
            await self.hot_search_repository.insert_candidates(
                diagnostic_top, batch_id=batch_id, computed_at=now, llm_samples=llm_samples
            )
            stats.duration_ms = int((time.monotonic() - started) * 1000)
            await self.hot_search_repository.update_batch_run(stats, computed_at=now)

            try:
                await self.hot_search_repository.purge_old_diagnostics(keep_batches=self.config.diagnostic_keep_batches)
            except Exception:
                logger.warning("hot-search diagnostics purge failed tenant={}", self.tenant_id)

            return stats
        except Exception as exc:
            logger.exception("hot-search rebuild failed tenant={} batch={}", self.tenant_id, batch_id)
            stats.status = "failed"
            stats.error_message = f"{type(exc).__name__}: {exc}"[:500]
            stats.duration_ms = int((time.monotonic() - started) * 1000)
            try:
                await self.hot_search_repository.update_batch_run(stats, computed_at=now)
            except Exception:
                logger.warning("hot-search failed-run record write failed tenant={}", self.tenant_id)
            raise
        finally:
            try:
                await self.redis_repository.release_lock(self.tenant_id)
            except Exception:
                logger.warning("hot-search lock release failed tenant={}", self.tenant_id)
