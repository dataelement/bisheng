"""租户自动开通的内部命令及回执端口。"""

from bisheng.department.application.external_tenant_anchor import ensure_external_tenant_anchor
from bisheng.tenant.domain.repositories.external_provision import (
    ExternalTenantCommand,
    ExternalTenantOperation,
    ExternalTenantReceipt,
    TenantExternalProvisionRepository,
)
from bisheng.tenant.domain.services.external_provision import TenantExternalProvisionService

__all__ = [
    "ExternalTenantCommand",
    "ExternalTenantOperation",
    "ExternalTenantReceipt",
    "KunlianExternalTenantApplication",
    "TenantExternalProvisionRepository",
]


class KunlianExternalTenantApplication:
    def __init__(self, repository, *, anchor_provider=ensure_external_tenant_anchor, structure_projector=None):
        self.repository = repository
        self.service = TenantExternalProvisionService(
            repository, anchor_provider=anchor_provider, structure_projector=structure_projector
        )

    async def reserve_external_tenant(self, command, *, expected_fence=None):
        return await self.repository.reserve(command, expected_fence=expected_fence)

    async def ensure_external_tenant(self, command, *, operation):
        return await self.service.ensure(command, operation=operation)

    async def read_external_tenant_receipt(self, operation):
        return await self.repository.read_receipt(operation)

    async def set_external_tenant_policy(self, source_key, *, expected_revision, enabled):
        return await self.repository.set_policy(source_key, expected_revision=expected_revision, enabled=enabled)

    async def read_external_tenant_state(self, source_key):
        return await self.repository.read_source_state(source_key)
