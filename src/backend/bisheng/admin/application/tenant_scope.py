"""Read the current management narrowing without middleware fail-open fallback."""

from bisheng.admin.domain.services.tenant_scope import TenantScopeService


async def current_admin_scope(user_id: int) -> int | None:
    return (await TenantScopeService.get_scope(user_id))["scope_tenant_id"]
