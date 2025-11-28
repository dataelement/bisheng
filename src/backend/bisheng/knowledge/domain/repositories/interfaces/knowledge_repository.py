from abc import ABC

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge import Knowledge


class KnowledgeRepository(BaseRepository[Knowledge, int], ABC):
    """知识库仓库接口"""
    pass
