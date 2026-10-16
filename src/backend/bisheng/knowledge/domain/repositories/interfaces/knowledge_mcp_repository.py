from abc import ABC, abstractmethod
from typing import Any

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class KnowledgeMcpRepository(BaseRepository[KnowledgeFile, int], ABC):
    @abstractmethod
    async def get_space(self, knowledge_id: int) -> Knowledge | None: ...

    @abstractmethod
    async def spaces(
        self, ids: list[int], *, name: str | None = None, after: list | None = None, limit: int = 100
    ) -> list[Knowledge]: ...

    @abstractmethod
    async def scan_files(
        self,
        space_ids: list[int],
        *,
        file_type: int,
        parent_path: str | None = None,
        recursive: bool = False,
        statuses: list[int] | None = None,
        after: list | None = None,
        sort_by: str = "update_time",
        order: str = "desc",
        limit: int = 100,
    ) -> list[KnowledgeFile]: ...

    @abstractmethod
    async def content_refs(self, files: list[KnowledgeFile]) -> dict[int, tuple[int, int, int]]: ...

    @abstractmethod
    async def content_matches(self, files: list[KnowledgeFile], keyword: str) -> set[int]: ...

    @abstractmethod
    async def chunks(
        self, file: KnowledgeFile, ref: tuple[int, int, int], *, from_index: int, limit: int = 100
    ) -> list[dict[str, Any]]: ...
