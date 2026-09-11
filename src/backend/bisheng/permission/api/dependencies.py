"""Dependency ports for the F048 permission HTTP boundary.

Endpoint modules depend on these application-level protocols. Concrete
runtime adapters are installed during application initialization; tests can
override the provider functions through FastAPI dependency overrides.
"""

from __future__ import annotations

from typing import Any, Protocol

from bisheng.permission.domain.schemas import (
    CatalogDraftRequest,
    CatalogPublishRequest,
    GrantMutationRequest,
    PermissionModeApplyRequest,
    PermissionModeDraftRequest,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)


class CatalogApiPort(Protocol):
    """Application contract consumed by Catalog endpoints."""

    async def get_current(self) -> Any: ...

    async def create_draft(
        self,
        *,
        request: CatalogDraftRequest,
        operator_id: int,
    ) -> Any: ...

    async def get_draft(
        self,
        *,
        draft_id: int,
        operator_id: int,
    ) -> Any: ...

    async def publish_draft(
        self,
        *,
        draft_id: int,
        request: CatalogPublishRequest,
        operator_id: int,
    ) -> Any: ...


class ResourcePermissionApiPort(Protocol):
    """Application contract for verified resource permission operations."""

    async def get_grantable_models(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
    ) -> Any: ...

    async def get_context(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
    ) -> Any: ...

    async def list_grants(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
        cursor: str | None,
        page_size: int,
    ) -> Any: ...

    async def get_my_permissions(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
    ) -> Any: ...

    async def mutate_grants(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
        request: GrantMutationRequest,
    ) -> Any: ...

    async def create_mode_draft(
        self,
        *,
        resource_type: str,
        resource_id: str,
        actor: PermissionActor,
        request: PermissionModeDraftRequest,
    ) -> Any: ...

    async def apply_mode_draft(
        self,
        *,
        resource_type: str,
        resource_id: str,
        draft_id: str,
        actor: PermissionActor,
        request: PermissionModeApplyRequest,
    ) -> Any: ...


class PermissionDecisionApiPort(Protocol):
    """Application contract for concrete action decisions."""

    async def check(
        self,
        *,
        resource_type: str,
        resource_id: str,
        action: str,
        actor: PermissionActor,
    ) -> bool: ...


_catalog_api: CatalogApiPort | None = None
_resource_permission_api: ResourcePermissionApiPort | None = None
_permission_decision_api: PermissionDecisionApiPort | None = None


def configure_catalog_api(api: CatalogApiPort) -> None:
    """Install the process-wide Catalog application adapter."""

    global _catalog_api
    _catalog_api = api


async def get_catalog_api() -> CatalogApiPort:
    """Return the configured Catalog adapter."""

    from bisheng.permission.application.process_runtime import get_f048_process_runtime

    await get_f048_process_runtime()
    if _catalog_api is None:
        raise RuntimeError("F048 Catalog API adapter is not configured")
    return _catalog_api


def configure_resource_permission_api(api: ResourcePermissionApiPort) -> None:
    """Install the process-wide resource permission application adapter."""

    global _resource_permission_api
    _resource_permission_api = api


async def get_resource_permission_api() -> ResourcePermissionApiPort:
    """Return the configured resource permission adapter."""

    from bisheng.permission.application.process_runtime import get_f048_process_runtime

    await get_f048_process_runtime()
    if _resource_permission_api is None:
        raise RuntimeError("F048 resource permission API is not configured")
    return _resource_permission_api


def configure_permission_decision_api(api: PermissionDecisionApiPort) -> None:
    """Install the concrete-action decision application adapter."""

    global _permission_decision_api
    _permission_decision_api = api


async def get_permission_decision_api() -> PermissionDecisionApiPort:
    """Return the configured decision adapter."""

    from bisheng.permission.application.process_runtime import get_f048_process_runtime

    await get_f048_process_runtime()
    if _permission_decision_api is None:
        raise RuntimeError("F048 permission decision API is not configured")
    return _permission_decision_api
