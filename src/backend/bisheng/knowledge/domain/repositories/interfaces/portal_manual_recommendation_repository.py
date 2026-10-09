from abc import ABC, abstractmethod
from dataclasses import dataclass

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


@dataclass(frozen=True)
class ManualFileRecord:
    file: KnowledgeFile
    space_name: str
    space_level: str
    canonical_document_id: int | None
    canonical_version_id: int | None


class PortalManualRecommendationRepository(BaseRepository[KnowledgeFile, int], ABC):
    @abstractmethod
    async def list_spaces(self) -> list[dict]: ...

    @abstractmethod
    async def list_files(
        self, space_id: int, q: str, page: int, page_size: int
    ) -> tuple[list[ManualFileRecord], int]: ...

    @abstractmethod
    async def find_references(self, references: list[dict]) -> list[ManualFileRecord]: ...
