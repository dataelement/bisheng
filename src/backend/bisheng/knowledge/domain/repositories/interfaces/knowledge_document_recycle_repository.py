"""文档回收事务所需的持久化接口。"""

from abc import ABC, abstractmethod
from collections.abc import Iterable

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_recycle_item import KnowledgeRecycleItem

DocumentRecycleContext = tuple[
    KnowledgeDocument | None, list[KnowledgeFile], list[KnowledgeDocumentVersion], list[KnowledgeFile]
]
RecycleSnapshotContext = tuple[int, dict[int, Knowledge], dict[int, str], dict[int, KnowledgeFile]]


class KnowledgeDocumentRecycleRepository(BaseRepository[KnowledgeRecycleItem, int], ABC):
    @abstractmethod
    async def load_document(self, document_id: int) -> DocumentRecycleContext:
        """锁定文档并读取入口、版本和物理文件。"""

    @abstractmethod
    async def snapshot_context(self, files: Iterable[KnowledgeFile]) -> RecycleSnapshotContext:
        """读取保留期、知识库及原目录名称。"""

    @abstractmethod
    async def document_items(self, document_id: int) -> list[KnowledgeRecycleItem]:
        """读取该文档的回收快照。"""

    @abstractmethod
    async def remove_document_items(self, document_id: int) -> None:
        """移除快照但不提交事务。"""

    @abstractmethod
    async def restore_conflicts(self, manager: KnowledgeFile, knowledge_id: int) -> list[int]:
        """检查目标库仍有效的同名或同内容文件。"""
