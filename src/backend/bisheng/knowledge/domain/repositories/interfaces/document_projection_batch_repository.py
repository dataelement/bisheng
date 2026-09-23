"""批量投影的持久化领取与条件写回接口。"""

from abc import abstractmethod

from bisheng.knowledge.domain.contracts.document_projection_batch import ProjectionBatchContext
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository


class DocumentProjectionBatchRepository(KnowledgeFileRepository):
    @abstractmethod
    async def claim_batch(
        self,
        ids: list[int],
        owner: str,
        max_attempts: int,
        *,
        handoff_owner: str | None = None,
    ) -> ProjectionBatchContext: ...

    @abstractmethod
    async def renew(self, owner: str, expected_ids: list[int] | None = None) -> None: ...

    @abstractmethod
    async def settle(
        self,
        snapshots: list[KnowledgeFile],
        owner: str,
        errors: dict[int, str],
        max_attempts: int,
        *,
        finalizing: bool = False,
        rebuild_ids: set[int] | None = None,
        rebuild_owner: str | None = None,
    ) -> dict[int, str]: ...

    @abstractmethod
    async def release(self, owner: str) -> None: ...
