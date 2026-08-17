"""Application ports shared by F050 permission-setting workflows."""

from __future__ import annotations

from typing import Protocol

from bisheng.permission.application.control_state import (
    RuntimeCatalogSnapshot,
    RuntimeModelSnapshot,
)


class ProspectiveGrantRuntimePort(Protocol):
    """Read the current Catalog through the initialized F048 runtime."""

    async def prospective_owner_grantable_models(
        self,
    ) -> tuple[RuntimeCatalogSnapshot, tuple[RuntimeModelSnapshot, ...]]: ...


class ProspectiveGrantSubjectDirectoryPort(Protocol):
    """List active candidates inside a business-verified tenant scope."""

    async def list_users(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        keyword: str,
        page: int,
        page_size: int,
    ) -> dict[str, object]: ...

    async def list_user_groups(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        keyword: str,
        page: int,
        page_size: int,
    ) -> dict[str, object]: ...

    async def list_department_children(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        parent_id: int | None,
    ) -> list[dict[str, object]]: ...

    async def search_departments(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        keyword: str,
        limit: int,
    ) -> dict[str, object]: ...

    async def get_department_path(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        department_id: int,
    ) -> dict[str, object]: ...


class ProspectiveGrantApplicationPort(Protocol):
    """Permission operations available before a business resource exists."""

    async def get_context(self, **kwargs: object) -> dict[str, object]: ...
