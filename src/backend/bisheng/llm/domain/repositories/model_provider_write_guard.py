"""The original status/config writers participate in the provider fence."""

from sqlalchemy import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeProcessingConflictError
from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.repositories.model_provider_operation_repository import (
    ACTIVE_STATES,
    ModelProviderOperationRepository,
)
from bisheng.resource_reference.application.contracts import TransactionIdentity
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


async def alock_idle_model(session, model_id):
    """Read the parent identity, then lock provider before any model mutation."""
    tenant, transaction = ModelProviderOperationRepository._native(session)
    with session.no_autoflush, strict_tenant_filter():
        server_id = (
            await session.execute(select(LLMModel.server_id).where(LLMModel.id == model_id))
        ).scalar_one_or_none()
    transaction.assert_current(session)
    if ReferenceRepository.current_tenant_id() != tenant:
        raise KnowledgeOperationPlanChangedError()
    if server_id is None:
        raise LLMModelNotAccessibleError()
    repository = ModelProviderOperationRepository()
    await repository.alock_provider(session, server_id=server_id)
    await repository.arequire_idle(session, server_id=server_id)
    transaction.assert_current(session)
    return tenant, server_id, transaction


def lock_idle_model(session, model_id):
    tenant = ReferenceRepository.current_tenant_id()
    transaction = TransactionIdentity.capture(session)
    with session.no_autoflush, strict_tenant_filter():
        server_id = session.execute(select(LLMModel.server_id).where(LLMModel.id == model_id)).scalar_one_or_none()
        if server_id is None:
            raise LLMModelNotAccessibleError()
        provider = session.execute(
            select(LLMServer.id).where(LLMServer.id == server_id, LLMServer.tenant_id == tenant).with_for_update()
        ).scalar_one_or_none()
        if provider is None:
            raise LLMModelNotAccessibleError()
        busy = session.execute(
            select(KnowledgeOperationPlan.id)
            .where(
                KnowledgeOperationPlan.tenant_id == tenant,
                KnowledgeOperationPlan.model_server_id == server_id,
                KnowledgeOperationPlan.model_execution_state.in_(ACTIVE_STATES),
            )
            .limit(1)
        ).first()
    transaction.assert_current(session)
    if ReferenceRepository.current_tenant_id() != tenant:
        raise KnowledgeOperationPlanChangedError()
    if busy:
        raise KnowledgeProcessingConflictError(reason="model_provider_operation_active")
    return tenant, server_id, transaction


def check_idle_model_write(session, tenant, transaction):
    transaction.assert_current(session)
    if ReferenceRepository.current_tenant_id() != tenant or session.new or session.dirty or session.deleted:
        raise KnowledgeOperationPlanChangedError()
