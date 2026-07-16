from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from bisheng.knowledge.domain.services.portal_recommendation_pool_service import (
    PortalRecommendationPoolState,
)
from bisheng.knowledge.domain.services.portal_recommendation_service import PortalRecommendationCandidate


@dataclass(frozen=True, slots=True)
class PortalRecommendationPoolVersionState:
    desired_generation: int = 0
    active_generation: int = 0
    active_pool_version: str | None = None
    fingerprint: str | None = None


class PortalRecommendationRedisRepository(ABC):
    @abstractmethod
    async def increment_behavior_version(self, tenant_id: int, user_id: int) -> int: ...

    @abstractmethod
    async def get_behavior_version(self, tenant_id: int, user_id: int) -> int: ...

    @abstractmethod
    async def record_read(
        self,
        tenant_id: int,
        user_id: int,
        space_id: int,
        file_id: int,
        read_at: datetime,
    ) -> None: ...

    @abstractmethod
    async def record_read_and_increment_behavior_version(
        self,
        tenant_id: int,
        user_id: int,
        space_id: int,
        file_id: int,
        read_at: datetime,
    ) -> int:
        """Atomically persist the read state and advance the behavior version."""
        ...

    @abstractmethod
    async def list_recent_reads(
        self,
        tenant_id: int,
        user_id: int,
        *,
        now: datetime | None = None,
    ) -> dict[tuple[int, int], datetime]: ...

    @abstractmethod
    async def replace_interest(
        self,
        tenant_id: int,
        user_id: int,
        entries: Sequence[tuple[str, float]],
        ttl_seconds: int,
    ) -> None: ...

    @abstractmethod
    async def get_interest(self, tenant_id: int, user_id: int) -> list[tuple[str, float]]: ...

    @abstractmethod
    async def set_user_domains(
        self,
        tenant_id: int,
        user_id: int,
        domain_codes: Sequence[str],
        *,
        ttl_seconds: int = 1800,
    ) -> None: ...

    @abstractmethod
    async def get_user_domains(self, tenant_id: int, user_id: int) -> list[str] | None: ...

    @abstractmethod
    async def invalidate_user(self, tenant_id: int, user_id: int) -> None: ...

    @abstractmethod
    async def set_top_n(
        self,
        tenant_id: int,
        user_id: int,
        config_version: int,
        pool_version: str,
        behavior_version: int,
        ids: Sequence[tuple[int, int]],
        *,
        ttl_seconds: int = 240,
        scope: str = "base",
    ) -> None: ...

    @abstractmethod
    async def get_top_n(
        self,
        tenant_id: int,
        user_id: int,
        config_version: int,
        pool_version: str,
        behavior_version: int,
        *,
        scope: str = "base",
    ) -> list[tuple[int, int]] | None: ...

    @abstractmethod
    async def replace_pool(
        self,
        tenant_id: int,
        pool_version: str,
        pool_name: str,
        entries: Sequence[tuple[PortalRecommendationCandidate, float]],
    ) -> None: ...

    @abstractmethod
    async def get_pool(
        self,
        tenant_id: int,
        pool_version: str,
        pool_name: str,
        *,
        limit: int = 10_000,
        offset: int = 0,
    ) -> list[PortalRecommendationCandidate]: ...

    @abstractmethod
    async def get_pool_size(self, tenant_id: int, pool_version: str, pool_name: str) -> int: ...

    @abstractmethod
    async def mark_pool_version_ready(self, tenant_id: int, pool_version: str) -> None: ...

    @abstractmethod
    async def is_pool_version_ready(self, tenant_id: int, pool_version: str) -> bool: ...

    @abstractmethod
    async def acquire_pool_rebuild_trigger(self, tenant_id: int, *, ttl_seconds: int = 300) -> bool: ...

    @abstractmethod
    async def replace_hot_rotation_states(
        self,
        tenant_id: int,
        pool_version: str,
        pool_name: str,
        states: Mapping[tuple[int, int], PortalRecommendationPoolState],
    ) -> None: ...

    @abstractmethod
    async def get_hot_rotation_states(
        self,
        tenant_id: int,
        pool_version: str,
        pool_name: str,
    ) -> dict[tuple[int, int], PortalRecommendationPoolState]: ...

    @abstractmethod
    async def increment_desired_generation(self, tenant_id: int) -> int: ...

    @abstractmethod
    async def get_pool_state(self, tenant_id: int) -> PortalRecommendationPoolVersionState: ...

    @abstractmethod
    async def activate_pool_if_current(
        self,
        tenant_id: int,
        generation: int,
        pool_version: str,
        fingerprint: str,
    ) -> bool: ...

    @abstractmethod
    async def set_reconcile_watermark(self, tenant_id: int, update_time: datetime, file_id: int) -> None: ...

    @abstractmethod
    async def get_reconcile_watermark(self, tenant_id: int) -> tuple[datetime, int] | None: ...
