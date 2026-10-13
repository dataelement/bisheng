"""知识文档统计所需的只读身份查询契约。"""

from abc import ABC, abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class KnowledgeStatisticsRepository(BaseRepository[KnowledgeFile, int], ABC):
    @staticmethod
    @abstractmethod
    def aliases(identities: set[str]) -> dict[int, str]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def identities(file_ids: list[int]) -> dict[int, str]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def category_audit_sources(file_ids: list[int], document_ids: list[int]) -> dict:
        """有界读取当前入口、版本和有效管理来源, 不修改任何元数据。"""
        raise NotImplementedError
