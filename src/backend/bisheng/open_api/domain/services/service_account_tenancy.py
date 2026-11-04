"""Live business eligibility; credential lifecycle and permission subjects stay independent."""

from loguru import logger

from bisheng.common.errcode.open_api import (
    OpenApiAuthDependencyUnavailableError,
    OpenApiAuthError,
    OpenApiCredentialInvalidError,
    ServiceAccountInactiveError,
    ServiceAccountOwnerTenantMismatchError,
    ServiceAccountOwnerTenantUnresolvedError,
)
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.repositories.owner_repository import OwnerRepository


def _require_unique_tenant(tenant_ids: tuple[int, ...], expected_tenant_id: int) -> None:
    if len(tenant_ids) != 1:
        raise ServiceAccountOwnerTenantUnresolvedError()
    if tenant_ids[0] != expected_tenant_id:
        raise ServiceAccountOwnerTenantMismatchError()


async def require_owner_tenant(owner_user_id: int, tenant_id: int) -> None:
    try:
        tenants = await OwnerRepository.get_execution_owner_tenant_ids(owner_user_id)
        _require_unique_tenant(tenants, tenant_id)
    except OpenApiAuthError:
        raise
    except Exception as exc:
        logger.opt(exception=True).warning("open_api frozen owner tenancy lookup failed")
        raise OpenApiAuthDependencyUnavailableError() from exc


async def revalidate_service_account(principal: OpenApiPrincipal) -> OpenApiPrincipal:
    if principal.actor_kind != "service_account":
        return principal
    try:
        binding = await OwnerRepository.get_service_account_execution_binding(principal.actor_id)
        if binding is None:
            raise ServiceAccountInactiveError()
        account = binding.account
        if account.tenant_id != principal.tenant_id:
            raise OpenApiCredentialInvalidError()
        if not account.is_enabled:
            raise ServiceAccountInactiveError()
        if not binding.owner_exists:
            raise ServiceAccountOwnerTenantUnresolvedError()
        _require_unique_tenant(binding.owner_tenant_ids, principal.tenant_id)
        return principal.model_copy(
            update={"resource_owner_user_id": account.resource_owner_user_id, "actor_name": account.name}
        )
    except OpenApiAuthError:
        raise
    except Exception as exc:
        logger.opt(exception=True).warning("open_api service account tenancy lookup failed")
        raise OpenApiAuthDependencyUnavailableError() from exc
