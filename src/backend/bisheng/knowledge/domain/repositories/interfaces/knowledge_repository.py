from abc import ABC
from collections.abc import Sequence

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge import Knowledge


class KnowledgeRepository(BaseRepository[Knowledge, int], ABC):
    """Knowledge Base Repository Interface"""

    async def find_file_sync_spaces(
        self,
        *,
        allowed_space_ids: set[int] | None,
        keyword: str | None,
        after: tuple[int, str, int] | None,
        limit: int,
    ) -> Sequence[tuple[Knowledge, str]]: ...

    async def find_file_sync_spaces_by_ids(
        self,
        space_ids: set[int],
    ) -> Sequence[tuple[Knowledge, str]]: ...
