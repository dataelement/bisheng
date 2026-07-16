"""Interface for hot-search snapshot / batch-run / candidate persistence (F048)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

from bisheng.knowledge.domain.schemas.portal_hot_search_schema import (
    HotSearchBatchStats,
    HotSearchRankItem,
    PortalHotSearchItem,
)


class PortalHotSearchRepository(ABC):
    @abstractmethod
    async def insert_batch_run(
        self,
        stats: HotSearchBatchStats,
        *,
        window_start: datetime,
        window_end: datetime,
        computed_at: datetime,
    ) -> None:
        """Insert the initial (running) batch-run row."""

    @abstractmethod
    async def update_batch_run(
        self,
        stats: HotSearchBatchStats,
        *,
        computed_at: datetime,
    ) -> None:
        """Update the batch-run row with final counts/status."""

    @abstractmethod
    async def replace_snapshot(
        self,
        items: Sequence[HotSearchRankItem],
        *,
        batch_id: str,
        computed_at: datetime,
    ) -> None:
        """Whole-batch replace of the tenant snapshot with the published Top-K."""

    @abstractmethod
    async def insert_candidates(
        self,
        items: Sequence[HotSearchRankItem],
        *,
        batch_id: str,
        computed_at: datetime,
        llm_samples: dict[str, str] | None = None,
    ) -> None:
        """Persist Top-N candidate diagnostics (incl. non-ranked)."""

    @abstractmethod
    async def list_home_snapshot(self, *, top_k: int) -> list[PortalHotSearchItem]:
        """Return the current tenant snapshot ordered by rank."""

    @abstractmethod
    async def purge_old_diagnostics(self, *, keep_batches: int) -> None:
        """Retain only the most recent ``keep_batches`` batches per tenant."""
