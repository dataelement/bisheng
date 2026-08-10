from __future__ import annotations

from abc import ABC, abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope


class KnowledgeSpaceScopeRepository(BaseRepository[KnowledgeSpaceScope, int], ABC):
    @abstractmethod
    async def find_by_space_id(self, space_id: int) -> KnowledgeSpaceScope | None: ...

    @abstractmethod
    async def find_by_space_ids(self, space_ids: list[int]) -> list[KnowledgeSpaceScope]: ...

    @abstractmethod
    async def list_portal_candidates(self, *, tenant_id: int) -> list[KnowledgeSpaceScope]: ...

    @abstractmethod
    async def set_portal_discovery_enabled(
        self,
        *,
        space_id: int,
        enabled: bool,
    ) -> KnowledgeSpaceScope: ...

    @abstractmethod
    async def update_space_and_portal_discovery(
        self,
        *,
        space: Knowledge,
        enabled: bool,
        department_binding: DepartmentKnowledgeSpace | None = None,
    ) -> KnowledgeSpaceScope:
        """在同一事务中提交知识库主表、门户开关与可选部门 binding。"""

    @abstractmethod
    async def stage_space_and_portal_discovery(
        self,
        *,
        space: Knowledge,
        enabled: bool,
    ) -> KnowledgeSpaceScope:
        """在当前 session 暂存主表与开关, 由同一 Unit of Work 稍后提交。"""
