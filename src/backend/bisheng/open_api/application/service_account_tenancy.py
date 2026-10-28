"""Public eligibility interfaces; callers never access ownership repositories."""

from bisheng.open_api.domain.services.service_account_tenancy import (
    require_owner_tenant,
    revalidate_service_account,
)

__all__ = ["require_owner_tenant", "revalidate_service_account"]
