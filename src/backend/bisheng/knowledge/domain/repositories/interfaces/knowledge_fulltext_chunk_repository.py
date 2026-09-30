from abc import ABC, abstractmethod

from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextChunk,
    KnowledgeFulltextChunkSource,
)


class KnowledgeFulltextChunkRepository(ABC):
    @abstractmethod
    async def list_many(self, sources: list[KnowledgeFulltextChunkSource]) -> dict[int, list[KnowledgeFulltextChunk] | Exception]: ...

    @abstractmethod
    async def list_all(
        self,
        *,
        source: KnowledgeFulltextChunkSource,
    ) -> list[KnowledgeFulltextChunk]: ...
