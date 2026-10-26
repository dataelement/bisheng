"""Business validation for the unified skill authorization runtime."""

from hashlib import sha256

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.linsight.domain.repositories.skill_permission import SkillPermissionRepository
from bisheng.permission.domain.schemas import VerifiedPermissionTarget


class SkillPermissionAdapter:
    def __init__(self, runtime, repository=None):
        self.runtime = runtime
        self.repository = repository or SkillPermissionRepository()

    async def resolve_permission_target(self, *, resource_id, actor, action):
        row = await self.repository.get(int(resource_id)) if resource_id.isdigit() else None
        if row is None or row.tenant_id != actor.current_tenant_id:
            raise PermissionInvalidResourceError()
        if row.source == "personal" and (actor.subject_type != "user" or row.created_by != actor.user_id):
            raise PermissionInvalidResourceError()
        if action == "use" and not row.enabled:
            raise PermissionInvalidResourceError()
        version, context = await self.runtime.get_permission_version(
            tenant_id=row.tenant_id,
            resource_type="linsight_skill",
            resource_id=str(row.id),
        )
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=row.tenant_id,
            resource_type="linsight_skill",
            resource_id=str(row.id),
            resource_version=version,
            context_version=sha256(f"{context}|{row.update_time}|{row.source}|{row.enabled}".encode()).hexdigest(),
        )


async def ensure_builtin_skill_permission(skill):
    from bisheng.permission.application.process_runtime import get_f048_process_runtime
    from bisheng.permission.application.system_resource_reconcile import (
        SystemOwnedResourceSpec,
        reconcile_system_owned_resources,
    )

    runtime = (await get_f048_process_runtime()).components.facade
    await reconcile_system_owned_resources(
        runtime,
        (
            SystemOwnedResourceSpec(
                tenant_id=skill.tenant_id,
                resource_type="linsight_skill",
                resource_id=str(skill.id),
                action_codes=("use", "visible"),
                context_version=f"skill:{skill.id}",
            ),
        ),
        apply=True,
        operator_id=1,
    )
