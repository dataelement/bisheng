"""门户全文高级检索的 ES 只读端口。"""

from abc import ABC, abstractmethod
from typing import Any

from bisheng.knowledge.domain.schemas.knowledge_fulltext_search_schema import (
    KnowledgeFulltextAdvancedSearchQuery,
    KnowledgeFulltextSearchBatch,
    KnowledgeFulltextUploaderSupport,
)


class KnowledgeFulltextSearchRepository(ABC):
    @abstractmethod
    async def open_pit(self) -> str: ...

    @abstractmethod
    async def search(
        self,
        query: KnowledgeFulltextAdvancedSearchQuery,
        *,
        pit_id: str,
        search_after: list[Any] | None,
        size: int,
    ) -> KnowledgeFulltextSearchBatch: ...

    @abstractmethod
    async def close_pit(self, pit_id: str) -> None: ...

    @abstractmethod
    async def find_uploader_supports(
        self,
        *,
        space_ids: list[int],
        uploader_ids: list[int],
        per_uploader_limit: int,
    ) -> list[KnowledgeFulltextUploaderSupport]: ...
