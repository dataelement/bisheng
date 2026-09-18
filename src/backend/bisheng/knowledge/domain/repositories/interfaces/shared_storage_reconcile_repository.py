"""对账查询与既有投影重建登记接口。"""

from abc import abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.contracts.shared_storage_reconcile import DocumentSnapshot
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument


class SharedStorageReconcileRepository(BaseRepository[KnowledgeDocument, int]):
    @abstractmethod
    async def upper_bound(self) -> int: ...

    @abstractmethod
    async def page_ids(self, after: int, upper: int, limit: int) -> list[int]: ...

    @abstractmethod
    async def snapshots(self, ids: list[int], *, lock: bool = False) -> dict[int, DocumentSnapshot]: ...

    @abstractmethod
    async def queue_rebuild(self, snapshot: DocumentSnapshot) -> int: ...
