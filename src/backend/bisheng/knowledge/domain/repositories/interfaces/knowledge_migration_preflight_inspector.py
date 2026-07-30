from abc import ABC, abstractmethod
from collections.abc import Sequence

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class KnowledgeMigrationPreflightInspector(ABC):
    @abstractmethod
    async def find_storage_errors(
        self,
        files: Sequence[KnowledgeFile],
    ) -> dict[int, str]: ...
