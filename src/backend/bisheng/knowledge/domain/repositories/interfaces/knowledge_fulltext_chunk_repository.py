from abc import ABC, abstractmethod

from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import KnowledgeFulltextChunk


class KnowledgeFulltextChunkRepository(ABC):
    @abstractmethod
    async def list_all(
        self,
        *,
        index_name: str,
        file_id: int,
        knowledge_id: int,
    ) -> list[KnowledgeFulltextChunk]: ...
