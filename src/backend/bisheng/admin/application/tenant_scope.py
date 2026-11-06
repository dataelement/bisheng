"""Read the current management narrowing without middleware fail-open fallback."""

from dataclasses import dataclass
from typing import Literal

from bisheng.admin.domain.repositories.tenant_scope_repository import TenantScopeRepository
from bisheng.admin.domain.services.tenant_scope import TenantScopeService
from bisheng.common.errcode.admin_scope import (
    AdminScopeChangedError,
    AdminScopeTenantRequiredError,
    AdminScopeUnavailableError,
)
from bisheng.common.errcode.tenant import TenantDisabledError, TenantNotFoundError


@dataclass(frozen=True, slots=True)
class EffectiveManagementScope:
    tenant_id: int
    source: Literal["selected", "own"]
    expires_at: str | None


async def resolve_management_scope(
    user_id: int, *, is_super: bool, for_write: bool = False
) -> EffectiveManagementScope:
    value = await TenantScopeService.get_scope(user_id, is_super=is_super, for_write=for_write)
    tenant_id = value.get("scope_tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0 or value.get("source") not in {"selected", "own"}:
        raise AdminScopeUnavailableError()
    return EffectiveManagementScope(tenant_id=tenant_id, source=value["source"], expires_at=value.get("expires_at"))


def require_expected_management_tenant(expected: str | None, scope: EffectiveManagementScope) -> None:
    if expected is None:
        raise AdminScopeTenantRequiredError()
    if not expected.isascii() or not expected.isdigit() or int(expected) != scope.tenant_id:
        raise AdminScopeChangedError(scope_tenant_id=scope.tenant_id)


async def current_admin_scope(user_id: int) -> int:
    return (await TenantScopeService.get_scope(user_id))["scope_tenant_id"]


async def ensure_service_account_tenant_available(tenant_id: int) -> None:
    status = await TenantScopeRepository.status(tenant_id)
    if status is None:
        raise TenantNotFoundError()
    if status != "active":
        raise TenantDisabledError()


async def read_service_account_scope(user_id: int) -> dict:
    return await TenantScopeService.get_scope(user_id)


async def set_service_account_scope(user_id: int, tenant_id: int, request_context: dict | None = None) -> dict:
    # The service-account service authenticates the global-super caller first.
    await ensure_service_account_tenant_available(tenant_id)
    return await TenantScopeService.set_scope(user_id, tenant_id, request_context)
