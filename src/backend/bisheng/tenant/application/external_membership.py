"""租户 Owner 的显式外部成员生命周期。权限只通过既有 application。"""

import asyncio

from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError
from bisheng.department.application.external_membership import ensure_external_department_membership
from bisheng.permission.application import (
    PermissionObject,
    PermissionRelation,
    PermissionRelationChange,
    PermissionSubject,
    get_permission_relation_api,
)
from bisheng.sso_sync.domain.schemas.kunlian import KunlianTenantMapping
from bisheng.tenant.domain.repositories.external_membership import ExternalMembershipRepository

__all__ = ["ExternalMembershipRepository", "KunlianExternalMembershipApplication"]


async def project_tenant_membership(user_id: int, local_tenant_id: int):
    if local_tenant_id == 1:
        return
    permissions = await get_permission_relation_api()
    await permissions.apply_changes(
        (
            PermissionRelationChange(
                action="grant",
                relation=PermissionRelation(
                    subject=PermissionSubject("user", str(user_id)),
                    relation="member",
                    resource=PermissionObject("tenant", str(local_tenant_id)),
                ),
            ),
        ),
        crash_safe=True,
    )
    # 兼容投影接口允许排队后返回。必须复核当前关系才能结束 Owner 事务。
    if not await permissions.check(
        subject=PermissionSubject("user", str(user_id)),
        relation="member",
        resource=PermissionObject("tenant", str(local_tenant_id)),
        consistency="HIGHER_CONSISTENCY",
    ):
        raise KunlianDependencyUnavailableError()


class KunlianExternalMembershipApplication:
    def __init__(
        self,
        repository: ExternalMembershipRepository,
        *,
        project_membership=project_tenant_membership,
        ensure_department_membership=ensure_external_department_membership,
    ):
        self.repository = repository
        self.project_membership = project_membership
        self.ensure_department_membership = ensure_department_membership

    async def validate_external_mapping_target(self, local_tenant_id: int) -> int:
        from bisheng.core.context.tenant import tenant_execution_scope

        with tenant_execution_scope(local_tenant_id):
            return await self.repository.validate_external_mapping_target(local_tenant_id)

    async def ensure_external_membership(self, user_id: int, verified_mapping: KunlianTenantMapping) -> None:
        try:
            async with asyncio.timeout(10):
                async with self.repository.membership_scope(user_id, verified_mapping):
                    await self.project_membership(user_id, verified_mapping.local_tenant_id)
                tenant = await self.repository.read_current_tenant(user_id, verified_mapping)
                await self.ensure_department_membership(user_id, tenant.id, tenant.root_dept_id)
        except TimeoutError:
            raise KunlianDependencyUnavailableError() from None

    async def read_current_tenant(self, user_id: int, verified_mapping: KunlianTenantMapping) -> int:
        tenant = await self.repository.read_current_tenant(user_id, verified_mapping)
        return tenant.id


async def resolve_external_tenant_if_any(user_id: int, *, repository=None, mapping_reader=None):
    """普通身份不访问 F118 控制表。专属身份缺映射时明确拒绝。"""
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.sso_sync.application.kunlian import resolve_external_tenant_mapping

    repository = repository or ExternalMembershipRepository()
    if user_id not in await repository.find_external_user_ids([user_id]):
        return None
    mapping = await (mapping_reader or resolve_external_tenant_mapping)(user_id)
    with tenant_execution_scope(mapping.local_tenant_id):
        return await repository.read_current_tenant(user_id, mapping)
