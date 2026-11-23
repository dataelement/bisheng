"""Business validation for the unified skill authorization runtime."""

from hashlib import sha256

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.linsight.domain.models.linsight_skill import SKILL_SOURCE_BUILTIN
from bisheng.linsight.domain.repositories.skill_permission import SkillPermissionRepository
from bisheng.permission.domain.schemas import VerifiedPermissionTarget


class SkillPermissionAdapter:
    def __init__(self, runtime, repository=None):
        self.runtime = runtime
        self.repository = repository or SkillPermissionRepository()

    async def load_permission_record(self, *, resource_id):
        return await self.repository.get(int(resource_id)) if resource_id.isdigit() else None

    async def resolve_permission_target(self, *, resource_id, actor, action):
        row = await self.load_permission_record(resource_id=resource_id)
        if row is None or row.tenant_id != actor.current_tenant_id:
            raise PermissionInvalidResourceError()
        owner_user_id = int(getattr(row, "owner_user_id", 0) or 0)
        personal_owner = owner_user_id or (row.created_by if row.source == "personal" else 0)
        if personal_owner and (actor.subject_type != "user" or personal_owner != actor.user_id):
            raise PermissionInvalidResourceError()
        # Disabled skills remain manageable; executable selection checks enabled.
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
    # A shared idempotency key does not exclude another live executor. Hold the
    # business row until projection/finalize finishes; a waiter then inspects
    # fresh permission state instead of reconciling an active STAGING journal.
    async with SkillPermissionRepository().lock(skill.id, tenant_id=skill.tenant_id) as current:
        if (
            current is None
            or current.tenant_id != skill.tenant_id
            or current.source != SKILL_SOURCE_BUILTIN
            or current.owner_user_id != 0
        ):
            raise PermissionInvalidResourceError()
        await reconcile_system_owned_resources(
            runtime,
            (
                SystemOwnedResourceSpec(
                    tenant_id=current.tenant_id,
                    resource_type="linsight_skill",
                    resource_id=str(current.id),
                    action_codes=("visible",),
                    context_version=f"skill:{current.id}",
                ),
            ),
            apply=True,
            operator_id=1,
        )
