from abc import ABC, abstractmethod

from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextAutoRepairSource,
    KnowledgeFulltextFileSnapshot,
)


class KnowledgeFulltextSourceRepository(ABC):
    @abstractmethod
    async def get_current_snapshot(self, file_id: int) -> KnowledgeFulltextFileSnapshot | None: ...

    @abstractmethod
    async def get_auto_repair_source(self, file_id: int) -> KnowledgeFulltextAutoRepairSource | None: ...

    @abstractmethod
    async def list_file_ids(
        self,
        *,
        knowledge_id: int,
        after_file_id: int | None,
        limit: int,
    ) -> list[int]: ...

    @abstractmethod
    async def list_backfill_file_ids(
        self,
        *,
        after_file_id: int,
        limit: int,
        knowledge_id: int | None = None,
        file_id: int | None = None,
    ) -> list[int]: ...

    @abstractmethod
    async def get_knowledge_index_name(self, knowledge_id: int) -> str | None: ...
