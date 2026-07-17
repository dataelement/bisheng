from abc import ABC, abstractmethod
from dataclasses import dataclass

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace


@dataclass(frozen=True)
class DepartmentSpaceRebindPlan:
    """Prepared database and permission changes for one department rebind."""

    space_id: int
    old_department_id: int
    new_department_id: int
    manager_grant_user_ids: tuple[int, ...] = ()
    manager_revoke_user_ids: tuple[int, ...] = ()
    revoke_old_department_viewer: bool = True
    is_noop: bool = False


class DepartmentSpaceBindingRepository(BaseRepository[DepartmentKnowledgeSpace, int], ABC):
    """部门知识库归属关系的事务仓储。"""

    @abstractmethod
    async def rebind_department(
        self,
        *,
        space_id: int,
        department_id: int,
        operator_id: int,
    ) -> DepartmentKnowledgeSpace:
        """在同一事务中更新 scope 与部门绑定关系。"""

    @abstractmethod
    async def prepare_rebind_department(
        self,
        *,
        space_id: int,
        department_id: int,
        operator_id: int,
        creator_user_id: int,
        old_admin_user_ids: set[int],
        new_admin_user_ids: set[int],
        revoke_old_department_viewer: bool = True,
    ) -> DepartmentSpaceRebindPlan:
        """Lock rows and stage binding plus department-admin membership changes."""

    @abstractmethod
    async def commit_prepared_rebind(self) -> DepartmentKnowledgeSpace:
        """Commit the staged rebind after external permission writes succeed."""

    @abstractmethod
    async def rollback_prepared_rebind(self) -> None:
        """Rollback a staged rebind without changing persisted database state."""
