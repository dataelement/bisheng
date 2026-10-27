from abc import ABC, abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class KnowledgeFileOrganizationRepository(BaseRepository[KnowledgeFile, int], ABC):
    @abstractmethod
    async def primary_organization(self, user_id: int, tenant_id: int) -> int | None: ...

    @abstractmethod
    def primary_organization_sync(self, user_id: int, tenant_id: int) -> int | None: ...

    @abstractmethod
    async def publish_organization_context(self, source_id: int, target_id: int) -> tuple: ...

    @abstractmethod
    async def set_document_organization(
        self, document_id: int, tenant_id: int, organization_id: int | None
    ) -> None: ...
