"""SQLModel implementation of the hot-search persistence repository (F048)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.knowledge.domain.models.portal_hot_search_snapshot import (
    PortalHotSearchBatchRun,
    PortalHotSearchCandidate,
    PortalHotSearchSnapshot,
)
from bisheng.knowledge.domain.repositories.interfaces.portal_hot_search_repository import (
    PortalHotSearchRepository,
)
from bisheng.knowledge.domain.schemas.portal_hot_search_schema import (
    HotSearchBatchStats,
    HotSearchRankItem,
    PortalHotSearchItem,
)


class PortalHotSearchRepositoryImpl(PortalHotSearchRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert_batch_run(
        self,
        stats: HotSearchBatchStats,
        *,
        window_start: datetime,
        window_end: datetime,
        computed_at: datetime,
    ) -> None:
        self.session.add(
            PortalHotSearchBatchRun(
                batch_id=stats.batch_id,
                status=stats.status,
                window_start=window_start,
                window_end=window_end,
                computed_at=computed_at,
            )
        )
        await self.session.flush()

    async def update_batch_run(
        self,
        stats: HotSearchBatchStats,
        *,
        computed_at: datetime,
    ) -> None:
        with strict_tenant_filter():
            result = await self.session.exec(
                select(PortalHotSearchBatchRun)
                .where(PortalHotSearchBatchRun.batch_id == stats.batch_id)
                .order_by(col(PortalHotSearchBatchRun.id).desc())
            )
        model = result.first()
        if model is None:
            await self.insert_batch_run(
                stats,
                window_start=computed_at,
                window_end=computed_at,
                computed_at=computed_at,
            )
            with strict_tenant_filter():
                result = await self.session.exec(
                    select(PortalHotSearchBatchRun)
                    .where(PortalHotSearchBatchRun.batch_id == stats.batch_id)
                    .order_by(col(PortalHotSearchBatchRun.id).desc())
                )
            model = result.first()
        model.status = stats.status
        model.scanned_count = stats.scanned_count
        model.distinct_query_count = stats.distinct_query_count
        model.candidate_count = stats.candidate_count
        model.dedup_record_count = stats.dedup_record_count
        model.qualified_count = stats.qualified_count
        model.llm_group_calls = stats.llm_group_calls
        model.llm_rewrite_calls = stats.llm_rewrite_calls
        model.llm_degraded = 1 if stats.llm_degraded else 0
        model.truncated = 1 if stats.truncated else 0
        model.duration_ms = stats.duration_ms
        model.es_pages = stats.es_pages
        model.error_message = stats.error_message
        model.computed_at = computed_at
        self.session.add(model)
        await self.session.flush()

    async def replace_snapshot(
        self,
        items: Sequence[HotSearchRankItem],
        *,
        batch_id: str,
        computed_at: datetime,
    ) -> None:
        with strict_tenant_filter():
            existing = await self.session.exec(select(PortalHotSearchSnapshot))
            for model in existing.all():
                await self.session.delete(model)
            await self.session.flush()
        for item in items:
            if item.final_rank is None:
                continue
            self.session.add(
                PortalHotSearchSnapshot(
                    rank_no=item.final_rank,
                    intent_key=item.intent_key,
                    display_query=item.display_query,
                    canonical_query=item.canonical_query,
                    heat_score=item.heat_score,
                    unique_users=item.unique_users,
                    search_count_7d=item.search_count_7d,
                    search_count_8_30d=item.search_count_8_30d,
                    batch_id=batch_id,
                    computed_at=computed_at,
                )
            )
        await self.session.flush()

    async def insert_candidates(
        self,
        items: Sequence[HotSearchRankItem],
        *,
        batch_id: str,
        computed_at: datetime,
        llm_samples: dict[str, str] | None = None,
    ) -> None:
        llm_samples = llm_samples or {}
        for item in items:
            self.session.add(
                PortalHotSearchCandidate(
                    batch_id=batch_id,
                    intent_key=item.intent_key,
                    canonical_query=item.canonical_query,
                    display_query=item.display_query,
                    member_queries=json.dumps(item.member_queries, ensure_ascii=False),
                    heat_score=item.heat_score,
                    unique_users=item.unique_users,
                    search_count_7d=item.search_count_7d,
                    search_count_8_30d=item.search_count_8_30d,
                    qualified=1 if item.qualified else 0,
                    final_rank=item.final_rank,
                    rewrite_source=item.rewrite_source,
                    llm_sample=llm_samples.get(item.intent_key),
                    computed_at=computed_at,
                )
            )
        await self.session.flush()

    async def list_home_snapshot(self, *, top_k: int) -> list[PortalHotSearchItem]:
        with strict_tenant_filter():
            result = await self.session.exec(
                select(PortalHotSearchSnapshot).order_by(col(PortalHotSearchSnapshot.rank_no))
            )
        rows = result.all()
        return [
            PortalHotSearchItem(rank=int(row.rank_no), query=row.display_query) for row in rows[: max(int(top_k), 0)]
        ]

    async def purge_old_diagnostics(self, *, keep_batches: int) -> None:
        keep = max(int(keep_batches), 0)
        for model in (PortalHotSearchBatchRun, PortalHotSearchCandidate):
            with strict_tenant_filter():
                result = await self.session.exec(
                    select(model.id, model.batch_id).order_by(col(model.computed_at).desc())
                )
            rows = result.all()
            kept_batches: list[str] = []
            for _row_id, batch_id in rows:
                if batch_id not in kept_batches:
                    kept_batches.append(batch_id)
            keep_batch_ids = set(kept_batches[:keep])
            stale_row_ids = [row_id for row_id, batch_id in rows if batch_id not in keep_batch_ids]
            if not stale_row_ids:
                continue
            # Delete by primary key so tenant scoping stays exact (bulk DELETE
            # is not intercepted by the tenant-filter SELECT hook).
            await self.session.exec(delete(model).where(col(model.id).in_(stale_row_ids)))
            await self.session.flush()
