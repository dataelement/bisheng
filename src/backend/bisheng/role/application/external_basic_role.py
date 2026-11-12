"""基础模板及受限事务锁端口。"""

from bisheng.role.domain.repositories.external_basic_role import (
    BASIC_MENUS,
    BasicRoleOperation,
    BasicRoleReceipt,
    RoleExternalBasicRoleRepository,
)
from bisheng.role.domain.services.external_basic_role import RoleExternalBasicRoleService

__all__ = [
    "BASIC_MENUS",
    "BasicRoleOperation",
    "BasicRoleReceipt",
    "ExternalBasicRoleApplication",
    "RoleExternalBasicRoleRepository",
    "mutate_managed_role",
]


class ExternalBasicRoleApplication:
    def __init__(self, repository):
        self.repository = repository
        self.service = RoleExternalBasicRoleService(repository)

    async def reserve_external_basic_role(self, connection_id, tenant_id):
        return await self.repository.reserve(connection_id, tenant_id)

    async def ensure_external_basic_role(self, operation):
        return await self.service.ensure(operation)

    async def read_external_basic_role(self, connection_id, tenant_id):
        async with self.repository.session(tenant_id) as session:
            async with self.lock_template(session, connection_id, tenant_id) as result:
                return result

    def lock_template(self, session, connection_id, tenant_id, *, expected_revision=None, require_applied=True):
        return self.repository.locked_template(
            session, connection_id, tenant_id, expected_revision=expected_revision, require_applied=require_applied
        )

    async def set_external_basic_role(self, connection_id, tenant_id, *, expected_revision, enabled):
        return await self.repository.set_policy(
            connection_id, tenant_id, expected_revision=expected_revision, enabled=enabled
        )

    async def find_managed_templates(self, role_ids):
        return await self.repository.find_managed(role_ids)


def get_repository():
    return RoleExternalBasicRoleRepository()


async def mutate_managed_role(role_id, *, fields=None, menus=None, remove=False):
    repository = get_repository()
    references = await repository.find_managed([role_id])
    if not references:
        return False
    return await repository.mutate(references[0], fields=fields, menus=menus, remove=remove)
