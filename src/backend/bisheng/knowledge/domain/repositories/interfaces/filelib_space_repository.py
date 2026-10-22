from abc import ABC, abstractmethod

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.interfaces.knowledge_mcp_repository import KnowledgeMcpRepository


class FilelibSpaceRepository(KnowledgeMcpRepository, ABC):
    @abstractmethod
    async def find_by_encoding(self, encoding: str, knowledge_id: int | None) -> list[KnowledgeFile]: ...

    @abstractmethod
    async def primary_flags(self, file_ids: list[int]) -> dict[int, bool]: ...

    @abstractmethod
    async def abstracts(self, files: list[KnowledgeFile]) -> dict[int, str]: ...

    @abstractmethod
    async def root_entries(self, knowledge_id: int) -> list[KnowledgeFile]: ...

    @abstractmethod
    async def persist_parse_result(self, file_id: int, status: int, remark: str = "") -> KnowledgeFile: ...

    @abstractmethod
    async def fresh_content_state(self, file_id: int) -> tuple | None: ...
