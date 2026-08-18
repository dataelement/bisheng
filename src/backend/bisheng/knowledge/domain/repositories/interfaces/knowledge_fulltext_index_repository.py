from abc import ABC, abstractmethod
from datetime import datetime

from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextDocument,
    KnowledgeFulltextEngagementBulkResult,
    KnowledgeFulltextEngagementCounts,
)


class KnowledgeFulltextIndexRepository(ABC):
    @abstractmethod
    async def validate_read_index(self) -> None: ...

    @abstractmethod
    async def ensure_index(self) -> None: ...

    @abstractmethod
    async def switch_alias(self, *, expected_current_index: str | None = None) -> None: ...

    @abstractmethod
    async def upsert(self, document: KnowledgeFulltextDocument) -> None: ...

    @abstractmethod
    async def bulk_update_engagement(
        self,
        counts: list[KnowledgeFulltextEngagementCounts],
        *,
        updated_at: datetime,
    ) -> KnowledgeFulltextEngagementBulkResult: ...

    @abstractmethod
    async def list_file_ids(
        self,
        *,
        after_file_id: int | None,
        limit: int,
    ) -> list[int]: ...

    @abstractmethod
    async def existing_file_ids(self, file_ids: list[int]) -> set[int]: ...

    @abstractmethod
    async def delete(self, file_id: int) -> None: ...

    @abstractmethod
    async def delete_scope(self, knowledge_id: int) -> None: ...
