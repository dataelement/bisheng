from abc import ABC, abstractmethod
from typing import Literal

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

DiscardResult = Literal["deleted", "retained", "stale"]


class UnreadableSyncFileRepository(BaseRepository[KnowledgeFile, int], ABC):
    @abstractmethod
    def discard(self, file: KnowledgeFile) -> DiscardResult:
        """在调用方事务内锁定并清理独立初始文件, 同时保存补偿清单。"""
        ...
