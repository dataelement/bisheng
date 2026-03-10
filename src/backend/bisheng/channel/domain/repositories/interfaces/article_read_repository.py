from abc import ABC, abstractmethod
from typing import Optional

from bisheng.channel.domain.models.article_read_record import ArticleReadRecord
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class ArticleReadRepository(BaseRepository[ArticleReadRecord, str], ABC):
    """Interface for Article Read Repository"""

    @abstractmethod
    async def find_by_user_and_article(self, user_id: int, article_id: str) -> Optional[ArticleReadRecord]:
        """Find an article read record by user ID and article ID"""
        pass

    @abstractmethod
    async def get_all_read_article_ids(self, user_id: int) -> list[str]:
        """Get all read article ids for a given user"""
        pass

    @abstractmethod
    async def find_article_ids_by_user_and_sources(self, user_id: int, source_ids: Optional[list[str]] = None) -> list[str]:
        """Find read article IDs by user ID and optional source IDs"""
        pass
