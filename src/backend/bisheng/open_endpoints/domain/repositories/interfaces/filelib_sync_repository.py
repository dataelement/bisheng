from __future__ import annotations

from abc import ABC, abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.database.models.department import Department, UserDepartment
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.user.domain.models.user import User


class FilelibSyncRepository(BaseRepository[KnowledgeFile, int], ABC):
    @abstractmethod
    async def find_user_by_id(self, user_id: int) -> User | None:
        pass

    @abstractmethod
    async def find_primary_department(self, user_id: int) -> UserDepartment | None:
        pass

    @abstractmethod
    async def find_department_by_id(self, department_id: int) -> Department | None:
        pass

    @abstractmethod
    async def find_department_by_name(self, name: str) -> Department | None:
        pass

    @abstractmethod
    async def find_department_space(self, department_id: int) -> DepartmentKnowledgeSpace | None:
        pass

    @abstractmethod
    async def find_public_space_by_name(self, name: str) -> Knowledge | None:
        pass

    @abstractmethod
    async def find_knowledge_by_id(self, knowledge_id: int) -> Knowledge | None:
        pass
