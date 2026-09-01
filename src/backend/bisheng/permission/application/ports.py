"""Application ports shared by F050 permission-setting workflows."""

from __future__ import annotations

from typing import Protocol

from bisheng.permission.application.control_state import (
    RuntimeCatalogSnapshot,
    RuntimeModelSnapshot,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_service import (
    CanonicalGrantChange,
    GrantMutationResult,
)
from bisheng.permission.domain.services.grant_source_service import GrantSourceRecord
from bisheng.permission.domain.services.permission_action_service import PermissionActor


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
        include_hidden: bool = False,
    ) -> dict[str, object]: ...

    async def list_user_tree_children(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        parent_id: int | None,
        user_page: int,
        user_page_size: int,
        include_hidden: bool = False,
    ) -> dict[str, object]: ...

    async def search_user_tree(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        keyword: str,
        limit: int,
        include_hidden: bool = False,
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


class InitialGrantRuntimePort(Protocol):
    """Durable F048 operations used after owner creation."""

    async def allocate_source_ids(self, count: int) -> tuple[int, ...]: ...

    async def mutate_grants(
        self,
        *,
        actor: PermissionActor,
        target: VerifiedPermissionTarget,
        changes: tuple[CanonicalGrantChange, ...],
        expected_resource_version: int,
        expected_catalog_release_id: int,
        idempotency_key: str,
    ) -> GrantMutationResult: ...


class InitialGrantSubjectDirectoryPort(Protocol):
    """Canonicalize active subjects in the verified target tenant."""

    async def canonical_source(
        self,
        *,
        tenant_id: int,
        source_id: int,
        subject_type: str,
        subject_id: str,
        userset_relation: str | None,
        include_children: bool,
    ) -> GrantSourceRecord: ...


class InitialGrantApplicationPort(Protocol):
    """Apply ADD-only ordinary Grants to a newly authorized resource."""

    async def apply(self, **kwargs: object) -> GrantMutationResult: ...
