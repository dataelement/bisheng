from typing import Any, Coroutine

from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository


class KnowledgeFileRepositoryImpl(BaseRepositoryImpl[KnowledgeFile, int], KnowledgeFileRepository):
    """知识库仓库实现类"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeFile)


    # 根据 knowledge_id和knowledge_file_ids 获取user_metadata 字段
    async def get_user_metadata_by_knowledge_file_ids(self, knowledge_id: int, knowledge_file_ids: list[int]) -> dict[
        int | None, list[dict[str, Any]] | None]:
        query = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            col(KnowledgeFile.id).in_(knowledge_file_ids)
        )

        result = await self.session.exec(query)

        knowledge_files = result.all()

        user_metadata_dict = {
            knowledge_file.id: knowledge_file.user_metadata for knowledge_file in knowledge_files
        }

        return user_metadata_dict

