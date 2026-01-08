from typing import Any, Coroutine

from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository


class KnowledgeFileRepositoryImpl(BaseRepositoryImpl[KnowledgeFile, int], KnowledgeFileRepository):
    """Knowledge Base Repository Implementation Class"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeFile)


    # according knowledge_idAndknowledge_file_ids Dapatkanuser_metadata Data field
    async def get_user_metadata_by_knowledge_file_ids(self, knowledge_id: int, knowledge_file_ids: list[int]) -> dict[
        int | None, list[dict[str, Any]] | None]:
        query = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            col(KnowledgeFile.id).in_(knowledge_file_ids)
        )

        result = await self.session.exec(query)

        knowledge_files = result.all()

        user_metadata_dict = {}

        for knowledge_file in knowledge_files:
            if knowledge_file.user_metadata:
                # Sort by newness
                sorted_user_metadata = dict(sorted(knowledge_file.user_metadata.items(), key=lambda item: item[1].get("updated_at", 0), reverse=False))
                user_metadata_dict[knowledge_file.id] = sorted_user_metadata
            else:
                user_metadata_dict[knowledge_file.id] = {}

        return user_metadata_dict

