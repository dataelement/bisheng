from abc import ABC

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge import Knowledge


class KnowledgeRepository(BaseRepository[Knowledge, int], ABC):
    """Knowledge Base Repository Interface"""
    pass
