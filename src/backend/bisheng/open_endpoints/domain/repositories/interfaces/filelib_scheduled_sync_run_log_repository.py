"""Run log repository contract for scheduled filelib sync jobs."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from bisheng.open_endpoints.domain.models.filelib_scheduled_sync_run_log import FilelibScheduledSyncRunLog


@dataclass(frozen=True)
class FilelibScheduledSyncRunLogCreate:
    tenant_id: int
    job_code: str
    trigger_type: str
    status: str
    start_time: datetime
    developer_token_id: int | None = None
    file_id: int | None = None
    knowledge_id: int | None = None
    file_name: str | None = None
    error_message: str | None = None
    end_time: datetime | None = None
    duration_ms: int | None = None


@dataclass(frozen=True)
class FilelibScheduledSyncRunLogUpdate:
    status: str | None = None
    developer_token_id: int | None = None
    file_id: int | None = None
    knowledge_id: int | None = None
    file_name: str | None = None
    error_message: str | None = None
    end_time: datetime | None = None
    duration_ms: int | None = None


class FilelibScheduledSyncRunLogRepository(ABC):
    @abstractmethod
    async def insert(self, payload: FilelibScheduledSyncRunLogCreate) -> int:
        """Persist a new run log row and return its id."""

    @abstractmethod
    async def update(self, run_id: int, payload: FilelibScheduledSyncRunLogUpdate) -> None:
        """Update an existing run log row."""

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: int,
        *,
        job_code: str,
        page: int,
        limit: int,
    ) -> tuple[list[FilelibScheduledSyncRunLog], int]:
        """Return paginated run logs ordered by id desc."""
