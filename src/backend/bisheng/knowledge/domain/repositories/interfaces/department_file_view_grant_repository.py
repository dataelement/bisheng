from __future__ import annotations

from abc import ABC, abstractmethod

from bisheng.knowledge.domain.models.department_file_view_grant import (
    DepartmentFileViewGrant,
)


class DepartmentFileViewGrantRepository(ABC):
    @abstractmethod
    async def list_by_user_and_files(
        self,
        *,
        tenant_id: int,
        user_id: int,
        resource_keys: set[tuple[int, int]],
    ) -> list[DepartmentFileViewGrant]: ...

    @abstractmethod
    async def list_active_by_user_and_files(
        self,
        *,
        tenant_id: int,
        user_id: int,
        resources: dict[tuple[int, int], int],
    ) -> dict[tuple[int, int], DepartmentFileViewGrant]: ...

    @abstractmethod
    async def invalidate_stale_active_by_user_and_files(
        self,
        *,
        tenant_id: int,
        user_id: int,
        resources: dict[tuple[int, int], int],
        reason: str,
    ) -> list[DepartmentFileViewGrant]: ...

    @abstractmethod
    async def activate(
        self,
        *,
        tenant_id: int,
        user_id: int,
        space_id: int,
        file_id: int,
        department_id: int,
        approval_instance_id: int,
    ) -> DepartmentFileViewGrant: ...

    @abstractmethod
    async def revoke(
        self,
        *,
        tenant_id: int,
        user_id: int,
        space_id: int,
        file_id: int,
        approval_instance_id: int,
        revoked_by: int,
        reason: str,
    ) -> DepartmentFileViewGrant | None: ...

    @abstractmethod
    async def invalidate_by_space(
        self,
        *,
        tenant_id: int,
        space_id: int,
        reason: str,
    ) -> list[DepartmentFileViewGrant]: ...

    @abstractmethod
    async def invalidate_by_file_ids(
        self,
        *,
        tenant_id: int,
        space_id: int,
        file_ids: set[int],
        reason: str,
    ) -> list[DepartmentFileViewGrant]: ...
