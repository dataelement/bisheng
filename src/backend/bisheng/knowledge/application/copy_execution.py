"""Worker entry binds trusted broker tenant, current actor and the persisted pair."""

from contextlib import contextmanager

from bisheng.common.errcode.knowledge import KnowledgeCPError
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter, tenant_execution_scope
from bisheng.knowledge.domain.repositories.copy_repository import CopyRepository


@contextmanager
def copy_execution_scope(tenant_id):
    from bisheng.worker.tenant_context import trusted_copy_tenant

    if tenant_id is None or trusted_copy_tenant.get() != tenant_id or get_current_tenant_id() != tenant_id:
        raise KnowledgeCPError(msg="Copy task has no matching trusted tenant header")
    with tenant_execution_scope(tenant_id), strict_tenant_filter():
        yield


def claim_copy(tenant_id, source_id, target_id, actor_id):
    source, _target = CopyRepository.inspect(tenant_id, source_id, target_id)
    assert_copy_actor(tenant_id, source, actor_id)
    return CopyRepository.claim(tenant_id, source_id, target_id, actor_id)


def assert_copy_actor(tenant_id, source, actor_id):
    from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
    from bisheng.role.application.effective_roles import load_effective_roles_sync
    from bisheng.user.domain.services.auth import LoginUser

    policy = load_effective_roles_sync(actor_id)
    if policy.home_tenant_id != tenant_id and not policy.is_identity_admin:
        raise KnowledgeCPError(msg="Copy actor tenant responsibility changed")
    from bisheng.permission.application.access import get_f048_runtime
    from bisheng.permission.application.identity import resolve_permission_actor
    from bisheng.permission.domain.schemas import VerifiedPermissionTarget
    from bisheng.utils.async_utils import run_async_safe

    async def check_current_permission():
        user = await LoginUser.init_login_user(actor_id, str(actor_id))
        record = await KnowledgeService._load_library_permission_record(source.id)
        if record is None or record.tenant_id != tenant_id or record.status != "COPYING":
            raise KnowledgeCPError()
        actor = await resolve_permission_actor(user)
        target = VerifiedPermissionTarget.from_business_service(
            tenant_id=tenant_id,
            resource_type="knowledge_library",
            resource_id=str(source.id),
            resource_version=record.permission_version,
            context_version=record.context_version,
        )
        if not await (await get_f048_runtime()).check_action(actor, target, "visible"):
            raise KnowledgeCPError(msg="Copy source is no longer authorized")
        await LoginUser.assert_effective_web_menu_contains(actor_id, "create_knowledge")

    run_async_safe(check_current_permission())


async def require_copy_ready(resource_ids):
    if await CopyRepository.pending_targets(resource_ids):
        raise KnowledgeCPError(msg="Knowledge copy is not ready")
