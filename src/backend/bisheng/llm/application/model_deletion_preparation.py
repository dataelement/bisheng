"""Release only the model Owner's already-created, pre-handoff reservation."""

from dataclasses import dataclass

from sqlalchemy import inspect as inspect_orm

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.core.context.tenant import management_tenant_scope, strict_tenant_filter, tenant_execution_scope
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.application.model_deletion_context import copied_metadata
from bisheng.llm.application.model_provider_projection import execution_metadata
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


@dataclass(frozen=True, slots=True, init=False)
class ModelDeletionPreparation:
    confirmation_id: str
    operation_id: str
    server_id: int
    tenant_id: int
    actor_user_id: int
    parent_confirmation_id: str

    @classmethod
    def from_plan(cls, row):
        if type(row) is not KnowledgeOperationPlan:
            raise KnowledgeOperationPlanChangedError()
        state, actor = inspect_orm(row), get_current_permission_actor()
        metadata = execution_metadata(row)
        if (
            not state.persistent
            or state.session is None
            or state.modified
            or row.tenant_id != ReferenceRepository.current_tenant_id()
            or row.operation != "model_share_server"
            or row.model_execution_state != "PREPARING"
            or actor is None
            or actor.subject_type != "user"
            or actor.subject_id != row.actor_user_id
            or metadata["purpose"] != "model_delete_prepare"
            or metadata["parent_confirmation_id"] is None
        ):
            raise KnowledgeOperationPlanChangedError()
        value = object.__new__(cls)
        values = (
            row.id,
            row.operation_id,
            row.model_server_id,
            row.tenant_id,
            row.actor_user_id,
            metadata["parent_confirmation_id"],
        )
        for name, item in zip(cls.__dataclass_fields__, values, strict=True):
            object.__setattr__(value, name, item)
        return value

    def check(self, row):
        metadata = execution_metadata(row)
        if (
            row.id != self.confirmation_id
            or row.tenant_id != self.tenant_id
            or row.operation != "model_share_server"
            or row.operation_id != self.operation_id
            or row.actor_user_id != self.actor_user_id
            or row.model_server_id != self.server_id
            or metadata["purpose"] != "model_delete_prepare"
            or metadata["parent_confirmation_id"] != self.parent_confirmation_id
        ):
            raise KnowledgeOperationPlanChangedError()


async def release_model_preparation(preparation, *, session_factory, repository):
    if type(preparation) is not ModelDeletionPreparation:
        raise KnowledgeOperationPlanChangedError()
    # This mechanical, narrower SQL scope is for one exact reservation that
    # this authenticated use case already created. No User or permission actor
    # is synthesized, and no model/target/sharing mutation is authorized here.
    with (
        tenant_execution_scope(preparation.tenant_id),
        management_tenant_scope(preparation.tenant_id),
        strict_tenant_filter(),
    ):
        async with session_factory() as session:
            async with session.begin():
                await repository.alock_provider(session, server_id=preparation.server_id)
                row = await repository.aread_plan(
                    session, confirmation_id=preparation.confirmation_id, lock=True, required=False
                )
                if row is None:
                    return  # The owning SQL phase rolled back before its commit.
                preparation.check(row)
                if row.model_execution_state == "COMPLETED":
                    return
                metadata = copied_metadata(row)
                metadata["ack"] = {"status": "released", "operation_id": row.operation_id}
                await repository.aset_state(
                    session, row=row, expected="PREPARING", target="COMPLETED", metadata=metadata
                )
