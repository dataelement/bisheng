"""分类浏览的跨页去重状态存储。"""

from abc import ABC, abstractmethod

from bisheng.knowledge.domain.schemas.knowledge_fulltext_search_schema import KnowledgeFulltextSearchSession


class KnowledgeFulltextCursorRepository(ABC):
    @abstractmethod
    async def save(self, state: KnowledgeFulltextSearchSession) -> str: ...

    @abstractmethod
    async def load(self, token: str) -> KnowledgeFulltextSearchSession | None: ...
