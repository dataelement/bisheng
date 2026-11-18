"""Retire failed model preparations without changing their signed payloads."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import inspect as inspect_orm

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.core.context.tenant import management_tenant_scope, strict_tenant_filter, tenant_execution_scope
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.application.model_deletion_context import execution_frame
from bisheng.llm.application.model_provider_projection import execution_metadata
from bisheng.llm.domain.repositories.model_delete_plan_repository import _hash, _utc
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.permission.application.model_sharing_projection import abandon_unstarted_model_sharing
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository

# A killed request cannot run its failure handler. Its persisted fence becomes
# recoverable after five minutes; this is not permission to discard unknown I/O.
MODEL_OPERATION_STALE_AFTER = timedelta(minutes=5)


@dataclass(frozen=True, slots=True, init=False)
class ModelSharingPreparation:
    confirmation_id: str
    operation_id: str
    server_id: int
    tenant_id: int
    actor_user_id: int
    request_hash: str
    plan_digest: str

    @classmethod
    def from_plan(cls, row):
        if type(row) is not KnowledgeOperationPlan:
            raise KnowledgeOperationPlanChangedError()
        state, actor = inspect_orm(row), get_current_permission_actor()
        if (
            not state.persistent
            or state.session is None
            or state.modified
            or row.tenant_id != ReferenceRepository.current_tenant_id()
            or row.operation != "model_share_server"
            or row.model_execution_state != "PREPARING"
            or execution_metadata(row) != execution_frame("model_share_server")
            or actor is None
            or not actor.super_admin
            or actor.subject_type != "user"
            or actor.subject_id != row.actor_user_id
        ):
            raise KnowledgeOperationPlanChangedError()
        receipt = object.__new__(cls)
        for name, value in zip(
            cls.__dataclass_fields__,
            (
                row.id,
                row.operation_id,
                row.model_server_id,
                row.tenant_id,
                row.actor_user_id,
                row.request_hash,
                row.plan_digest,
            ),
            strict=True,
        ):
            object.__setattr__(receipt, name, value)
        return receipt


def needs_recovery(row, now):
    ack = row.model_execution_metadata.get("ack") if isinstance(row.model_execution_metadata, dict) else None
    return (isinstance(ack, dict) and ack.get("status") == "retryable_failure") or (
        row.update_time is not None and _utc(row.update_time) + MODEL_OPERATION_STALE_AFTER <= _utc(now)
    )


async def abandon_unstarted(session, *, providers, row, actor_user_id):
    if row.operation != "model_share_server" or row.target_manifest != [] or row.space_id is not None:
        return False
    metadata = execution_metadata(row)
    if row.model_execution_state == "PREPARING":
        if metadata != execution_frame(
            metadata["purpose"], parent_confirmation_id=metadata["parent_confirmation_id"], force=metadata["force"]
        ):
            raise KnowledgeOperationPlanChangedError()
        if metadata["purpose"] not in {"model_share_server", "model_delete_prepare"}:
            return False
    elif row.model_execution_state == "RESERVED" and metadata["purpose"] == "model_share_server":
        providers.validate(row)
    else:
        return False
    journal_plan_id = metadata["parent_confirmation_id"] or row.id
    if not await abandon_unstarted_model_sharing(
        session, server_id=row.model_server_id, confirmation_id=journal_plan_id
    ):
        return False
    # Tombstoning a never-started preparation does not re-sign an old digest
    # (including records affected by historical DATETIME rounding).
    metadata = deepcopy(metadata)
    metadata["ack"] = {
        "status": "abandoned_unstarted",
        "cancel_actor_user_id": actor_user_id,
        "original_fingerprint": _hash(
            {
                "id": row.id,
                "operation_id": row.operation_id,
                "request_hash": row.request_hash,
                "plan_digest": row.plan_digest,
                "metadata": row.model_execution_metadata,
            }
        ),
    }
    await providers.aset_state(
        session, row=row, expected=row.model_execution_state, target="ABANDONED", metadata=metadata
    )
    return True


async def release_failed_sharing(preparation, *, session_factory, providers):
    """Mechanical cleanup of exactly the authenticated request's reservation."""
    if type(preparation) is not ModelSharingPreparation:
        raise KnowledgeOperationPlanChangedError()
    with (
        tenant_execution_scope(preparation.tenant_id),
        management_tenant_scope(preparation.tenant_id),
        strict_tenant_filter(),
    ):
        async with session_factory() as session:
            async with session.begin():
                await providers.alock_provider(session, server_id=preparation.server_id)
                row = await providers.aread_plan(
                    session, confirmation_id=preparation.confirmation_id, lock=True, required=False
                )
                if row is None or row.model_execution_state in {"COMPLETED", "ABANDONED", "SUPERSEDED"}:
                    return
                if (
                    row.operation_id != preparation.operation_id
                    or row.actor_user_id != preparation.actor_user_id
                    or row.model_server_id != preparation.server_id
                    or row.request_hash != preparation.request_hash
                    or row.plan_digest != preparation.plan_digest
                    or row.operation != "model_share_server"
                ):
                    raise KnowledgeOperationPlanChangedError()
                if await abandon_unstarted(
                    session, providers=providers, row=row, actor_user_id=preparation.actor_user_id
                ):
                    return
                # Started/unknown permission I/O must be reconciled, never unlocked
                # by timeout. The next authorized edit resumes the frozen journal.
                metadata = deepcopy(execution_metadata(row))
                metadata["ack"] = {"status": "retryable_failure", "operation_id": row.operation_id}
                await providers.aset_state(
                    session,
                    row=row,
                    expected=row.model_execution_state,
                    target=row.model_execution_state,
                    metadata=metadata,
                )
