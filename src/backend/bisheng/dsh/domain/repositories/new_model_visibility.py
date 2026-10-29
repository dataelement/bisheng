"""Initialize model grants in the same transaction that creates the models."""

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository


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
