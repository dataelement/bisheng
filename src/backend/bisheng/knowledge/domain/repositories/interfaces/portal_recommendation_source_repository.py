"""Current knowledge-file facts consumed by the rebuildable recommendation projection."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

from bisheng.knowledge.domain.services.portal_recommendation_projection_service import (
    PortalRecommendationSourceFile,
)


class PortalRecommendationSourceRepository(ABC):
    @abstractmethod
    async def find_by_id(self, file_id: int) -> PortalRecommendationSourceFile | None: ...

    @abstractmethod
    async def find_by_ids(self, file_ids: Sequence[int]) -> list[PortalRecommendationSourceFile]: ...

    @abstractmethod
    async def list_changed_after(
        self,
        *,
        update_time: datetime,
        file_id: int,
        limit: int,
    ) -> list[PortalRecommendationSourceFile]: ...

    @abstractmethod
    async def list_page(self, *, after_id: int, limit: int) -> list[PortalRecommendationSourceFile]: ...

    @abstractmethod
    async def list_for_resource(
        self,
        resource_type: str,
        resource_id: int,
        *,
        after_id: int,
        limit: int,
    ) -> list[PortalRecommendationSourceFile]: ...
