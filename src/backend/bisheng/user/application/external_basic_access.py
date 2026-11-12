"""用户基础资格对外协议, 与用户资料投影保持独立。"""

from dataclasses import replace

from bisheng.common.errcode.sso_sync import KunlianIdentityUnavailableError
from bisheng.user.domain.repositories.external_basic_access import (
    BasicAccessCommand,
    BasicAccessOperation,
    BasicAccessReceipt,
    UserExternalBasicAccessRepository,
)
from bisheng.user.domain.services.external_basic_access import UserExternalBasicAccessService

__all__ = [
    "BasicAccessCommand",
    "BasicAccessOperation",
    "BasicAccessReceipt",
    "ExternalBasicAccessApplication",
    "UserExternalBasicAccessRepository",
]


class ExternalBasicAccessApplication:
    def __init__(self, repository):
        self.repository = repository
        self.service = UserExternalBasicAccessService(repository)

    async def reserve_external_basic_access(self, command):
        return await self.repository.reserve(command)

    async def ensure_external_basic_access(self, command, *, operation):
        return await self.service.ensure(command, operation=operation)

    async def read_external_basic_access(self, connection_id, identity_key, tenant_id):
        return await self.repository.read(connection_id, identity_key, tenant_id)

    async def set_external_basic_access(self, connection_id, identity_key, tenant_id, *, expected_revision, enabled):
        return await self.repository.set_policy(
            connection_id, identity_key, tenant_id, expected_revision=expected_revision, enabled=enabled
        )

    async def read_current_qualification(self, user_id, *, identity_key, connection_id, tenant_id):
        from bisheng.user.application.external_identity import KunlianExternalIdentityApplication
        from bisheng.user.domain.repositories.external_identity_projection import (
            UserExternalIdentityProjectionRepository,
        )

        identity = KunlianExternalIdentityApplication(
            UserExternalIdentityProjectionRepository(self.repository.session_factory)
        )
        facts = await identity.read_current_qualification(user_id, identity_key=identity_key)
        access = await self.read_external_basic_access(connection_id, identity_key, tenant_id)
        if access.user_id != user_id:
            raise KunlianIdentityUnavailableError()
        managed = await self.repository.role_port.find_managed_templates(facts.role_ids)
        denied = {r.role_id for r in managed if not access.effective or r.role_id != access.role_id}
        # 独立人工角色继续交给原有效菜单及登录资格机制, 不创造新允许结果。
        return replace(facts, role_ids=tuple(r for r in facts.role_ids if r not in denied))

    async def require_login_access(self, user_id, *, identity_key, connection_id, tenant_id):
        from bisheng.user.application.external_identity import KunlianExternalIdentityApplication
        from bisheng.user.domain.repositories.external_identity_projection import (
            UserExternalIdentityProjectionRepository,
        )

        facts = await self.read_current_qualification(
            user_id, identity_key=identity_key, connection_id=connection_id, tenant_id=tenant_id
        )
        identity = KunlianExternalIdentityApplication(
            UserExternalIdentityProjectionRepository(self.repository.session_factory)
        )
        await identity.require_login_access(facts, local_tenant_id=tenant_id)
        return facts


def get_repository():
    return UserExternalBasicAccessRepository()


async def apply_managed_role_changes(user_id, *, add_ids, delete_ids, actor):
    return await get_repository().apply_role_mutation(user_id, add_ids=add_ids, delete_ids=delete_ids, actor=actor)
