"""Serialize the original Root provider sharing writers with model deletion."""

from copy import deepcopy

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeProcessingConflictError
from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao
from bisheng.llm.application.model_deletion_context import execution_frame, model_deletion_request, model_write_phase
from bisheng.llm.application.model_provider_projection import (
    ModelProjectionBinding,
    ModelProviderProjectionScope,
    execution_metadata,
)
from bisheng.llm.domain.repositories.model_delete_plan_repository import ModelDeletePlanRepository, _hash
from bisheng.llm.domain.repositories.model_deletion_repository import _revision
from bisheng.llm.domain.repositories.model_provider_operation_repository import ModelProviderOperationRepository
from bisheng.llm.domain.services.model_reference_service import ModelReferenceService
from bisheng.permission.application.model_sharing_projection import get_model_sharing_projection_application


class ModelSharingApplication:
    def __init__(
        self,
        *,
        references=None,
        plans=None,
        session_factory=get_async_db_session,
        sharing_factory=get_model_sharing_projection_application,
    ):
        self.references = references if references is not None else ModelReferenceService()
        self.plans = plans if plans is not None else ModelDeletePlanRepository()
        self.providers = ModelProviderOperationRepository(self.plans)
        self.session_factory, self.sharing_factory = session_factory, sharing_factory

    async def _permission(self, request, binding=None):
        scope = ModelProviderProjectionScope(
            session_factory=self.session_factory, repository=self.providers, binding=binding, guard=request.check
        )
        return await request.call(self.sharing_factory, scope=scope)

    async def _check_mounted(self, phase, mounted):
        if mounted is not None:
            from bisheng.llm.domain.repositories.model_mount_sharing_repository import ModelMountSharingRepository

            facts, _ = await phase.call(
                ModelMountSharingRepository().aread_mount,
                phase.session,
                **{name: getattr(mounted, name) for name in mounted.__dataclass_fields__},
            )
            if facts != mounted:
                raise KnowledgeOperationPlanChangedError()

    async def aresume_existing(self, *, identity, server_id, enabled):
        """Resume only an existing reservation from the original set-share command."""
        command = _hash(
            {"operation": "model_share_server", "server_id": server_id, "enabled": enabled, "child_id": None}
        )
        async with model_deletion_request(identity, references=self.references, plans=self.plans) as request:
            if request.tenant_id != ROOT_TENANT_ID or not request.actor.super_admin:
                raise LLMModelNotAccessibleError()
            async with model_write_phase(self.session_factory, request) as phase:
                await phase.call(self.providers.alock_provider, phase.session, server_id=server_id)
                row = await phase.call(self.providers.aactive_plan, phase.session, server_id=server_id)
                if row is None:
                    return False
                self.providers.validate(row)
                self.providers.require_current_actor(row, request.actor_reference)
                if (
                    row.operation != "model_share_server"
                    or execution_metadata(row)["purpose"] != "model_share_server"
                    or row.parameters["command_digest"] != command
                ):
                    raise KnowledgeProcessingConflictError(reason="model_provider_operation_active")
            await request.call(self.aset_sharing, identity=identity, server_id=server_id, enabled=enabled)
            return True

    async def aset_sharing(self, *, identity, server_id, enabled, child_id=None):
        if (
            type(server_id) is not int
            or server_id <= 0
            or type(enabled) is not bool
            or (child_id is not None and (type(child_id) is not int or child_id <= 0 or not enabled))
        ):
            raise KnowledgeOperationPlanChangedError()
        command = _hash(
            {"operation": "model_share_server", "server_id": server_id, "enabled": enabled, "child_id": child_id}
        )
        return await self._set_sharing(
            identity=identity, server_id=server_id, enabled=enabled, child_id=child_id, command=command
        )

    async def _set_sharing(self, *, identity, server_id, enabled, child_id, command, mounted=None):
        if mounted is not None:
            from bisheng.llm.domain.repositories.model_mount_sharing_repository import MountedModelShare

            if (
                type(mounted) is not MountedModelShare
                or command != mounted.digest(server_id)
                or child_id != mounted.child_id
            ):
                raise KnowledgeOperationPlanChangedError()
        async with model_deletion_request(identity, references=self.references, plans=self.plans) as request:
            if request.tenant_id != ROOT_TENANT_ID or not request.actor.super_admin:
                raise LLMModelNotAccessibleError()
            async with model_write_phase(self.session_factory, request) as phase:
                provider = await phase.call(self.providers.alock_provider, phase.session, server_id=server_id)
                await self._check_mounted(phase, mounted)
                if provider.tenant_id != ROOT_TENANT_ID:
                    raise LLMModelNotAccessibleError()
                row = await phase.call(self.providers.aactive_plan, phase.session, server_id=server_id)
                if row is None:
                    row = await phase.call(
                        self.providers.acreate_share_reservation,
                        phase.session,
                        server_id=server_id,
                        actor_reference=request.actor_reference,
                        server_revision=_revision(provider),
                        command_digest=command,
                        metadata=execution_frame("model_share_server"),
                    )
                else:
                    self.providers.validate(row)
                    metadata = execution_metadata(row)
                    self.providers.require_current_actor(row, request.actor_reference)
                    if (
                        row.operation != "model_share_server"
                        or metadata["purpose"] != "model_share_server"
                        or row.parameters["command_digest"] != command
                    ):
                        raise KnowledgeProcessingConflictError(reason="model_provider_operation_active")
                saved = deepcopy(row)
                binding = (
                    ModelProjectionBinding.from_plan(row, self.providers)
                    if row.model_execution_state == "RESERVED"
                    else None
                )
            sharing = await self._permission(request, binding)
            if saved.model_execution_state == "PREPARING":
                before = await request.call(sharing.aread, server_id=server_id)
                if child_id is not None:
                    children = await request.call(TenantDao.aget_children_ids_active, ROOT_TENANT_ID)
                    if child_id not in children:
                        raise LLMModelNotAccessibleError()
                    after = tuple(sorted(set(before.subjects) | {child_id}))
                elif enabled:
                    children = await request.call(TenantDao.aget_children_ids_active, ROOT_TENANT_ID)
                    after = tuple(sorted(set(before.subjects) | set(children)))
                else:
                    after = ()
                prepared = await request.call(
                    sharing.aprepare,
                    before=before,
                    after=after,
                    confirmation_id=saved.id,
                    actor=request.actor,
                    tenant_id=request.tenant_id,
                    operation="model_share_server",
                )
                async with model_write_phase(self.session_factory, request) as phase:
                    await phase.call(self.providers.alock_provider, phase.session, server_id=server_id)
                    await self._check_mounted(phase, mounted)
                    row = await phase.call(
                        self.providers.aread_plan, phase.session, confirmation_id=saved.id, lock=True
                    )
                    if row.operation_id != saved.operation_id or row.model_execution_state != "PREPARING":
                        raise KnowledgeOperationPlanChangedError()
                    self.providers.require_current_actor(row, request.actor_reference)
                    metadata = execution_frame("model_share_server")
                    metadata["sharing"] = prepared.metadata()
                    await phase.call(self.providers.abind, phase.session, row, server_id=server_id, metadata=metadata)
                    binding = ModelProjectionBinding.from_plan(row, self.providers)
                sharing = await self._permission(request, binding)
                await request.call(sharing.arequire_before, prepared)
            else:
                if saved.model_execution_state != "RESERVED":
                    raise KnowledgeOperationPlanChangedError()
                prepared = await request.call(
                    sharing.arestore,
                    execution_metadata(saved)["sharing"],
                    confirmation_id=saved.id,
                    tenant_id=saved.tenant_id,
                    operation=saved.operation,
                    operator_id=saved.actor_user_id,
                )
            await request.call(sharing.aexecute, prepared)
            async with model_write_phase(self.session_factory, request) as phase:
                await phase.call(self.providers.alock_provider, phase.session, server_id=server_id)
                await self._check_mounted(phase, mounted)
                row = await phase.call(self.providers.aread_plan, phase.session, confirmation_id=saved.id, lock=True)
                self.providers.require_current_actor(row, request.actor_reference)
                binding.check_scalar(
                    await phase.call(self.providers.ascalar_pin, phase.session, confirmation_id=row.id)
                )
                await phase.call(sharing.arequire_finalized, phase.session, prepared)
                metadata = deepcopy(execution_metadata(row))
                metadata["ack"] = {"status": "shared", "operation_id": row.operation_id}
                await phase.call(
                    self.providers.aset_state,
                    phase.session,
                    row=row,
                    expected="RESERVED",
                    target="COMPLETED",
                    metadata=metadata,
                )
            if not enabled:
                return list(prepared.before.subjects)
            if child_id is not None:
                return [child_id]
            active = await request.call(TenantDao.aget_children_ids_active, ROOT_TENANT_ID)
            return sorted(set(active) & set(prepared.after))


async def get_model_sharing_application():
    return ModelSharingApplication()
