"""Tenant-keyed aggregate portal configuration repository contract."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

SHOUGANG_PORTAL_CONFIG_KEY = "shougang_portal_config"


def portal_admin_config_physical_key(tenant_id: int) -> str:
    tenant_id = int(tenant_id)
    if tenant_id <= 0:
        raise ValueError("tenant_id must be positive")
    if tenant_id == 1:
        return SHOUGANG_PORTAL_CONFIG_KEY
    return f"{SHOUGANG_PORTAL_CONFIG_KEY}:t:{tenant_id}"


@dataclass(frozen=True)
class PortalAdminConfigRecord:
    key: str
    value: str
    comment: str | None = None


class PortalAdminConfigRepository(ABC):
    @abstractmethod
    async def get(self, tenant_id: int) -> PortalAdminConfigRecord | None:
        """Read the tenant's aggregate config without locking."""

    @abstractmethod
    async def get_for_update(self, tenant_id: int) -> PortalAdminConfigRecord | None:
        """Read and lock the tenant's physical config row."""

    @abstractmethod
    async def write_value(self, tenant_id: int, value: str) -> None:
        """Insert/update and flush the tenant's aggregate config without commit."""
