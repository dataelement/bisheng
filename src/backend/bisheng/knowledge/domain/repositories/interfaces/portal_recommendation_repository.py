"""Persistence contract for the rebuildable recommendation file projection."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PortalRecommendationProjectionUpsert:
    file_id: int
    space_id: int
    business_domain_code: str | None
    permission_scope: str
    recommendable: bool
    reason_code: str
    source_update_time: datetime
    projection_version: int


@dataclass(frozen=True)
class PortalRecommendationProjectionRecord(PortalRecommendationProjectionUpsert):
    id: int
    tenant_id: int


class PortalRecommendationRepository(ABC):
    @abstractmethod
    async def upsert(self, value: PortalRecommendationProjectionUpsert) -> bool:
        """Apply only a newer projection version and flush without commit."""

    @abstractmethod
    async def delete(self, file_id: int, projection_version: int) -> bool:
        """Delete only when the current projection is not newer than the event."""

    @abstractmethod
    async def find_by_file_ids(
        self,
        file_ids: Sequence[int],
    ) -> list[PortalRecommendationProjectionRecord]:
        """Load lightweight projections for scoring without file metadata."""

    @abstractmethod
    async def list_recommendable_by_domains(
        self,
        business_domain_codes: Sequence[str],
        *,
        limit: int,
        offset: int = 0,
        space_ids: Sequence[int] | None = None,
    ) -> list[PortalRecommendationProjectionRecord]:
        """Read newest current-tenant eligible projections in exact domains."""

    @abstractmethod
    async def list_latest_recommendable(
        self,
        *,
        space_ids: Sequence[int] | None,
        limit: int,
    ) -> list[PortalRecommendationProjectionRecord]:
        """Bounded latest fallback candidates, optionally narrowed by spaces."""

    @abstractmethod
    async def list_changed_after(
        self,
        *,
        update_time: datetime,
        file_id: int,
        limit: int,
    ) -> list[PortalRecommendationProjectionRecord]:
        """Watermark page ordered by update_time and file_id."""

    @abstractmethod
    async def list_page(
        self,
        *,
        after_id: int,
        limit: int,
    ) -> list[PortalRecommendationProjectionRecord]:
        """Stable ID page for full reconciliation."""
