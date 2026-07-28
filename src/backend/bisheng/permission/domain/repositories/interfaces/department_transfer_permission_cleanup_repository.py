from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
    DepartmentTransferPermissionCleanupEvent,
    DepartmentTransferPermissionCleanupItem,
)


class DepartmentTransferPermissionCleanupRepository(
    BaseRepository[DepartmentTransferPermissionCleanupEvent, int],
    ABC,
):
    @abstractmethod
    async def create_or_get_event(self, **kwargs) -> DepartmentTransferPermissionCleanupEvent: ...

    @abstractmethod
    async def find_active_matching_event(
        self,
        *,
        tenant_id: int,
        user_id: int,
        old_department_id: int,
        new_department_id: int,
        trigger_source: str,
    ) -> DepartmentTransferPermissionCleanupEvent | None: ...

    @abstractmethod
    async def activate_event(
        self,
        event_id: int,
        *,
        changed_at: datetime,
        deadline_at: datetime,
    ) -> DepartmentTransferPermissionCleanupEvent | None: ...

    @abstractmethod
    async def cancel_event(
        self,
        event_id: int,
        *,
        reason: str,
    ) -> DepartmentTransferPermissionCleanupEvent | None: ...

    @abstractmethod
    async def upsert_item(self, **kwargs) -> DepartmentTransferPermissionCleanupItem: ...

    @abstractmethod
    async def protect_item(self, **kwargs) -> DepartmentTransferPermissionCleanupItem: ...

    @abstractmethod
    async def claim_event(self, event_id: int, *, now: datetime) -> bool: ...

    @abstractmethod
    async def list_due_event_ids(self, *, now: datetime, limit: int) -> list[int]: ...
