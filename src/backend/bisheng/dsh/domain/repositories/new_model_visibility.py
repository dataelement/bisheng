"""Initialize model grants in the same transaction that creates the models."""

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository


def should_record_new_model_visibility(dsh_enabled: bool) -> bool:
    """Whether model creation writes the initial "everyone" visibility row.

    With DSH the row is mandatory (no row = hidden), so a missing tenant context
    keeps failing loudly. Without DSH a missing row already means "everyone", so
    the row is written whenever a tenant is in scope: it keeps the model visible
    if DSH is enabled later, and contexts without a tenant (initialization
    scripts, unscoped administration) keep working unchanged.
    """
    if dsh_enabled:
        return True
    from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed

    tenant_id = get_current_tenant_id()
    return type(tenant_id) is int and tenant_id >= 1 and not is_tenant_filter_bypassed()


async def initialize_new_model_visibility(session, models, actor: int):
    candidates = [model for model in models if model.model_type == "llm"]
    if not candidates:
        return
    await session.flush()
    tenant = require_tenant()
    if any(model.tenant_id != tenant or not model.id for model in candidates):
        raise DshOperationConflictError()

    def initialize(sync_session):
        repository = UnifiedPolicyRepository(sync_session)
        for model in candidates:
            repository.initialize_model_visibility(model.id, actor)

    await session.run_sync(initialize)
