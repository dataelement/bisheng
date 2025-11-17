from abc import ABC
from typing import Any

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class KnowledgeFileRepository(BaseRepository[KnowledgeFile, int], ABC):
    """知识库文件仓库接口类"""

    async def get_user_metadata_by_knowledge_file_ids(self, knowledge_id: int,
                                                      knowledge_file_ids: list[int]) ->dict[
        int | None, list[dict[str, Any]] | None]:
        """根据 knowledge_id和knowledge_file_ids 获取user_metadata 字段"""
        pass
