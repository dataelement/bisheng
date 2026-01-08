from abc import ABC
from typing import Any

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class KnowledgeFileRepository(BaseRepository[KnowledgeFile, int], ABC):
    """Knowledge Base File Repository Interface Class"""

    async def get_user_metadata_by_knowledge_file_ids(self, knowledge_id: int,
                                                      knowledge_file_ids: list[int]) ->dict[
        int | None, list[dict[str, Any]] | None]:
        """according knowledge_idAndknowledge_file_ids Dapatkanuser_metadata Data field"""
        pass
