from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Literal

from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextEngagementCounts,
    KnowledgeFulltextEngagementDaily,
    KnowledgeFulltextEngagementHistoryPage,
)

EngagementMetric = Literal["preview_count", "download_count"]


class KnowledgeFulltextEngagementRepository(ABC):
    @abstractmethod
    async def increment_daily(
        self,
        *,
        file_id: int,
        local_date: str,
        metric: EngagementMetric,
        updated_at: datetime,
    ) -> None: ...

    @abstractmethod
    async def get_totals(self, file_ids: list[int]) -> dict[int, KnowledgeFulltextEngagementCounts]: ...

    @abstractmethod
    async def aggregate_history_page(
        self,
        *,
        event_type: str,
        after_key: dict[str, Any] | None,
        page_size: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> KnowledgeFulltextEngagementHistoryPage: ...

    @abstractmethod
    async def set_daily_metric(
        self,
        records: list[KnowledgeFulltextEngagementDaily],
        *,
        metric: EngagementMetric,
        updated_at: datetime,
    ) -> list[int]: ...

    @abstractmethod
    async def refresh_daily(self) -> None: ...


class KnowledgeFulltextEngagementQueueRepository(ABC):
    @abstractmethod
    async def enqueue(self, *, file_id: int, now_epoch: int) -> bool: ...

    @abstractmethod
    async def claim(self, *, now_epoch: int, lease_owner: str, limit: int) -> list[int]: ...

    @abstractmethod
    async def ack(self, *, file_id: int, lease_owner: str) -> bool: ...

    @abstractmethod
    async def retry(self, *, file_id: int, lease_owner: str, now_epoch: int) -> bool: ...

    @abstractmethod
    async def reclaim_expired(self, *, now_epoch: int) -> int: ...

    @abstractmethod
    async def acquire_schedule(self) -> bool: ...

    @abstractmethod
    async def release_schedule(self) -> None: ...

    @abstractmethod
    async def acquire_history_lock(self, token: str) -> bool: ...

    @abstractmethod
    async def release_history_lock(self, token: str) -> bool: ...

    @abstractmethod
    async def load_history_cursor(self, stage: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def save_history_cursor(self, stage: str, cursor: dict[str, Any] | None) -> None: ...

    @abstractmethod
    async def clear_history_state(self) -> None: ...
