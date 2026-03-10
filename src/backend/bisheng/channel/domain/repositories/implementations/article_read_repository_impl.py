from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from bisheng.channel.domain.models.article_read_record import ArticleReadRecord
from bisheng.channel.domain.repositories.interfaces.article_read_repository import ArticleReadRepository
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl


class ArticleReadRepositoryImpl(BaseRepositoryImpl[ArticleReadRecord, str], ArticleReadRepository):
    """SQLAlchemy implementation of ArticleReadRepository"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ArticleReadRecord)

    async def find_by_user_and_article(self, user_id: int, article_id: str) -> Optional[ArticleReadRecord]:
        """Find an article read record by user ID and article ID"""
        statement = select(ArticleReadRecord).where(
            ArticleReadRecord.user_id == user_id,
            ArticleReadRecord.article_id == article_id
        )
        result = await self.session.exec(statement)
        return result.first()