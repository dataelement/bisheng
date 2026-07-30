"""为 worker 提供短事务 migration repository context。"""

from contextlib import asynccontextmanager

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_repository_impl import (
    KnowledgeMigrationRepositoryImpl,
)


class KnowledgeMigrationRepositoryContextFactoryImpl:
    def __call__(self):
        return self._context()

    @staticmethod
    @asynccontextmanager
    async def _context():
        async with get_async_db_session() as session:
            yield KnowledgeMigrationRepositoryImpl(session)
