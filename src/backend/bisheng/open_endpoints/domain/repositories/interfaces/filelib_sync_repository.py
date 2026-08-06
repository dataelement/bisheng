from __future__ import annotations

from abc import ABC, abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.database.models.department import Department, UserDepartment
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.open_endpoints.domain.models.filelib_department_mapping import FilelibDepartmentMapping
from bisheng.user.domain.models.user import User


class FilelibSyncRepository(BaseRepository[KnowledgeFile, int], ABC):
    @abstractmethod
    async def find_user_by_id(self, user_id: int) -> User | None:
        pass

    @abstractmethod
    async def find_users_by_external_id(
        self,
        external_id: str,
        *,
        tenant_id: int,
    ) -> list[User]:
        pass

    @abstractmethod
    async def find_primary_departments(self, user_id: int) -> list[UserDepartment]:
        pass

    @abstractmethod
    async def find_department_by_id(self, department_id: int) -> Department | None:
        pass

    @abstractmethod
    async def find_department_by_external_id(
        self,
        external_id: str,
        *,
        tenant_id: int,
    ) -> Department | None:
        pass

    @abstractmethod
    async def find_department_mapping_by_external_department_id(
        self,
        external_department_id: str,
    ) -> FilelibDepartmentMapping | None:
        pass

    @abstractmethod
    async def find_knowledge_by_id(self, knowledge_id: int) -> Knowledge | None:
        pass
