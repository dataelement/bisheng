"""Read the current management narrowing without middleware fail-open fallback."""

from bisheng.admin.domain.repositories.tenant_scope_repository import TenantScopeRepository
from bisheng.admin.domain.services.tenant_scope import TenantScopeService
from bisheng.common.errcode.tenant import TenantDisabledError, TenantNotFoundError


async def current_admin_scope(user_id: int) -> int | None:
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
