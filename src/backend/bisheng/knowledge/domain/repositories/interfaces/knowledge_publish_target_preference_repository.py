from abc import ABC, abstractmethod
from typing import Any

from bisheng.common.repositories.interfaces.base_repository import BaseRepository

PUBLISH_TARGET_LINK_TYPES = frozenset(
    {
        "publish_target_personal",
        "publish_target_team",
        "publish_target_department",
    }
)


class KnowledgePublishTargetPreferenceRepository(BaseRepository[Any, int], ABC):
    @abstractmethod
    async def get_detail(self, *, user_id: int, link_type: str) -> str | None: ...

    @abstractmethod
    async def save_detail(self, *, user_id: int, link_type: str, detail: str) -> None: ...
