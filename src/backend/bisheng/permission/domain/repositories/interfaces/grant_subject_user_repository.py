from __future__ import annotations

from abc import ABC, abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.permission.domain.models.grant_subject_user import (
    GrantSubjectDepartment,
    GrantSubjectUserCandidate,
    GrantSubjectUserDepartmentLink,
)
from bisheng.user.domain.models.user import User


class GrantSubjectUserRepository(BaseRepository[User, int], ABC):
    @abstractmethod
    async def list_visible_departments(self, *, tenant_id: int) -> list[GrantSubjectDepartment]: ...

    @abstractmethod
    async def list_candidates(
        self,
        *,
        tenant_id: int,
        visible_department_ids: tuple[int, ...],
        keyword: str,
        page: int,
        page_size: int,
        department_id: int | None,
        unassigned: bool,
    ) -> list[GrantSubjectUserCandidate]: ...

    @abstractmethod
    async def list_department_links(
        self,
        *,
        user_ids: tuple[int, ...],
        visible_department_ids: tuple[int, ...],
    ) -> list[GrantSubjectUserDepartmentLink]: ...
