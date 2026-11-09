"""The model Owner's complete ordinary/forced provider removal transaction."""

import asyncio
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import timedelta

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanChangedError,
    KnowledgeProcessingConflictError,
    ResourceReferenceConflictError,
)
from bisheng.core.database import get_async_db_session
from bisheng.llm.application.model_deletion_context import (
    ModelDeleteCommand,
    copied_metadata,
    execution_frame,
    model_deletion_request,
    model_write_phase,
)
from bisheng.llm.application.model_deletion_preparation import ModelDeletionPreparation, release_model_preparation
from bisheng.llm.application.model_deletion_result import completed_model_result
from bisheng.llm.application.model_provider_projection import (
    ModelProjectionBinding,
    ModelProviderProjectionScope,
    execution_metadata,
)
from bisheng.llm.domain.repositories.model_delete_plan_repository import ModelDeletePlanRepository
from bisheng.llm.domain.repositories.model_deletion_repository import _revision
from bisheng.llm.domain.repositories.model_mutation_repository import ModelMutationRepository
from bisheng.llm.domain.repositories.model_provider_operation_repository import ModelProviderOperationRepository
from bisheng.llm.domain.schemas import LLMModelInfo, LLMServerInfo
from bisheng.llm.domain.services.model_reference_service import ModelReferenceService
from bisheng.permission.application.model_sharing_projection import get_model_sharing_projection_application


@dataclass(slots=True)
class _Operation:
    confirmation_id: str
    plan_digest: str
    preparation: ModelDeletionPreparation | None
    inspection: object
    old_server: object
    old_models: tuple
    execution: object = None
    binding: object = None


class ModelDeletionApplication:
    def __init__(
        self,
        *,
        references=None,
        plans=None,
        session_factory=get_async_db_session,
        sharing_factory=get_model_sharing_projection_application,
        after_update=None,
        after_delete=None,
    ):
        self.references = references if references is not None else ModelReferenceService()
        if not isinstance(self.references, ModelReferenceService):
            raise TypeError("the actual model reference Core is required")
        self.plans = plans if plans is not None else ModelDeletePlanRepository()
        self.providers, self.writer = ModelProviderOperationRepository(self.plans), ModelMutationRepository()
        self.session_factory, self.sharing_factory = session_factory, sharing_factory
        self.after_update, self.after_delete = after_update, after_delete

    async def arequire_idle(self, *, server_id):
        # A non-removal PUT keeps its original entry and validation path.
        # This factual busy check adds no Coverage or confirmation gate.
        async with self.session_factory() as session:
            async with session.begin():
                await self.providers.alock_provider(session, server_id=server_id)
                await self.providers.arequire_idle(session, server_id=server_id)

    async def areplay_completed_update(self, *, identity, server):
        from bisheng.llm.application.model_deletion_replay import find_completed_update

        found = await find_completed_update(self, identity=identity, server=server)
        if found is None:
            return None
        return await self.aupdate_server(
            identity=identity, server=server, confirmation_id=found[0], plan_digest=found[1]
        )

    @staticmethod
    def _check_command(row, command, providers, request):
        providers.validate(row)
        providers.require_current_actor(row, request.actor_reference)
        if (
            row.operation != command.operation
            or row.parameters["command_digest"] != command.command_digest
            or (command.confirmation_id is not None and row.id != command.confirmation_id)
            or (command.plan_digest is not None and row.plan_digest != command.plan_digest)
        ):
            raise KnowledgeOperationPlanChangedError()

    def _match_inspection(self, row, command, inspection, *, reserved=False):
        if (
            row.target_manifest != self.plans._manifest(inspection.targets)
            or row.target_revisions[f"server:{command.server_id}"] != inspection.server_revision
            or row.impact
            != {
                "inbound_digest": inspection.inbound_digest,
                "coverage_epoch": inspection.coverage_epoch,
                "inventory_hash": inspection.inventory_hash,
            }
        ):
            raise KnowledgeOperationPlanChangedError()
        actual = {f"model:{key.target_id}": revision for key, revision in inspection.target_revisions}
        expected = (
            execution_metadata(row)["reserved_target_revisions"]
            if reserved
            else {key: value for key, value in row.target_revisions.items() if key.startswith("model:")}
        )
        if actual != expected:
            raise KnowledgeOperationPlanChangedError()

    @staticmethod
    def _require_mode(command, inspection):
        if inspection.blocked and not command.force:
            raise ResourceReferenceConflictError(reason="model_referenced", impact=asdict(inspection))
        if command.operation == "model_update_server" and not inspection.targets:
            raise KnowledgeOperationPlanChangedError()

    async def _inspect(self, phase, command, *, execution=None):
        return await phase.call(
            self.references._aprepare_removed_models,
            phase.session,
            identity=phase.request.identity,
            server_id=command.server_id,
            retained_model_ids=command.retained,
            delete_server=command.operation == "model_delete_server",
            execution=execution,
        )

    async def _discover(self, request, command, progress):
        async with model_write_phase(self.session_factory, request) as phase:
            row = None
            if command.confirmation_id is None:
                previous = await phase.call(
                    self.providers.afind_completed,
                    phase.session,
                    server_id=command.server_id,
                    operation=command.operation,
                    actor_user_id=request.actor.subject_id,
                    command_digest=command.command_digest,
                )
                if previous is not None and execution_metadata(previous)["force"] == command.force:
                    self._check_command(previous, command, self.providers, request)
                    replay = command.operation == "model_delete_server"
                    if not replay:
                        provider, models = await phase.call(
                            self.writer.aread_result, phase.session, server_id=command.server_id
                        )
                        replay = self.writer.result_digest(provider, models) == execution_metadata(previous)["ack"].get(
                            "result_digest"
                        )
                    if replay:
                        return _Operation(
                            previous.id, previous.plan_digest, None, None, None, (), execution=deepcopy(previous)
                        )
            if command.confirmation_id is not None:
                row = await phase.call(
                    self.providers.aread_plan, phase.session, confirmation_id=command.confirmation_id
                )
                self._check_command(row, command, self.providers, request)
                if row.model_execution_state == "COMPLETED":
                    return _Operation(row.id, row.plan_digest, None, None, None, (), execution=deepcopy(row))
            await phase.call(self.providers.alock_provider, phase.session, server_id=command.server_id)
            active = await phase.call(self.providers.aactive_plan, phase.session, server_id=command.server_id)
            if active is not None and active.operation != "model_share_server":
                self._check_command(active, command, self.providers, request)
                if execution_metadata(active)["force"] != command.force:
                    raise KnowledgeOperationPlanChangedError()
                binding = None
                if execution_metadata(active)["sharing"] is not None:
                    binding = ModelProjectionBinding.from_plan(active, self.providers)
                old_server, old_models = await phase.call(
                    self.writer.aread_result, phase.session, server_id=command.server_id
                )
                return _Operation(
                    active.id,
                    active.plan_digest,
                    None,
                    None,
                    old_server,
                    old_models,
                    execution=deepcopy(active),
                    binding=binding,
                )
            preparation = None
            if active is not None:
                metadata = execution_metadata(active)
                if metadata["purpose"] != "model_delete_prepare":
                    raise KnowledgeProcessingConflictError(reason="model_provider_operation_active")
                self.providers.require_current_actor(active, request.actor_reference)
                if (
                    metadata["purpose"] != "model_delete_prepare"
                    or active.parameters["command_digest"] != command.command_digest
                    or metadata["force"] != command.force
                ):
                    raise KnowledgeOperationPlanChangedError()
                preparation = ModelDeletionPreparation.from_plan(active)
                progress["preparation"] = preparation
                row = await phase.call(
                    self.providers.aread_plan, phase.session, confirmation_id=preparation.parent_confirmation_id
                )
                self._check_command(row, command, self.providers, request)
            prepared = await self._inspect(phase, command)
            self._require_mode(command, prepared.inspection)
            if command.server is not None:
                await phase.call(
                    self.writer.arequire_unique_name,
                    phase.session,
                    server_id=command.server_id,
                    name=command.server.name,
                )
            if row is not None:
                row = await phase.call(
                    self.plans.aget_model_delete_plan_for_execution,
                    phase.session,
                    confirmation_id=row.id,
                    operation=command.operation,
                    actor_reference=request.actor_reference,
                    command_digest=command.command_digest,
                    plan_digest=row.plan_digest,
                )
                self._match_inspection(row, command, prepared.inspection)
            else:
                confirmation = await phase.call(
                    self.plans.acreate_model_delete_plan,
                    phase.session,
                    operation=command.operation,
                    actor_reference=request.actor_reference,
                    command_digest=command.command_digest,
                    targets=prepared.inspection.targets,
                    target_revisions={
                        **{f"model:{key.target_id}": value for key, value in prepared.inspection.target_revisions},
                        f"server:{command.server_id}": prepared.inspection.server_revision,
                    },
                    inbound_digest=prepared.inspection.inbound_digest,
                    coverage_epoch=prepared.inspection.coverage_epoch,
                    inventory_hash=prepared.inspection.inventory_hash,
                    expires_at=self.plans.clock() + timedelta(seconds=300),
                )
                row = await phase.call(
                    self.providers.aread_plan, phase.session, confirmation_id=confirmation.confirmation_id
                )
            old_server, old_models = await phase.call(
                self.writer.aread_result, phase.session, server_id=command.server_id
            )
            if preparation is None:
                metadata = execution_frame("model_delete_prepare", parent_confirmation_id=row.id, force=command.force)
                fence = await phase.call(
                    self.providers.acreate_share_reservation,
                    phase.session,
                    server_id=command.server_id,
                    actor_reference=request.actor_reference,
                    server_revision=_revision(old_server),
                    command_digest=command.command_digest,
                    metadata=metadata,
                )
                preparation = ModelDeletionPreparation.from_plan(fence)
                progress["preparation"] = preparation
            return _Operation(row.id, row.plan_digest, preparation, prepared.inspection, old_server, old_models)

    async def _sharing(self, request, *, binding=None):
        scope = ModelProviderProjectionScope(
            session_factory=self.session_factory, repository=self.providers, binding=binding, guard=request.check
        )
        return await request.call(self.sharing_factory, scope=scope)

    async def _prepare_sharing(self, request, command, operation):
        if request.tenant_id != 1:
            return None, None
        sharing = await self._sharing(request)
        before = await request.call(sharing.aread, server_id=command.server_id)
        if command.operation == "model_delete_server" or not command.server.share_to_children:
            after = ()
        else:
            from bisheng.database.models.tenant import TenantDao

            active = await request.call(TenantDao.aget_children_ids_active, 1)
            after = tuple(sorted(set(before.subjects) | set(active)))
        prepared = await request.call(
            sharing.aprepare,
            before=before,
            after=after,
            confirmation_id=operation.confirmation_id,
            actor=request.actor,
            tenant_id=request.tenant_id,
            operation=command.operation,
        )
        return sharing, prepared

    async def _handoff(self, request, command, operation, prepared_sharing):
        from uuid import uuid4

        async with model_write_phase(self.session_factory, request) as phase:
            await phase.call(self.providers.alock_provider, phase.session, server_id=command.server_id)
            await phase.call(
                self.providers.arequire_idle,
                phase.session,
                server_id=command.server_id,
                allowed_operation_id=operation.preparation.operation_id,
            )
            prepared = await self._inspect(phase, command)
            self._require_mode(command, prepared.inspection)
            row = await phase.call(
                self.plans.aget_model_delete_plan_for_execution,
                phase.session,
                confirmation_id=operation.confirmation_id,
                operation=command.operation,
                actor_reference=request.actor_reference,
                command_digest=command.command_digest,
                plan_digest=operation.plan_digest,
            )
            self._match_inspection(row, command, prepared.inspection)
            await phase.call(
                self.plans.aconsume_model_delete_plan,
                phase.session,
                confirmation_id=row.id,
                operation=command.operation,
                actor_reference=request.actor_reference,
                command_digest=command.command_digest,
                plan_digest=row.plan_digest,
                operation_id=str(uuid4()),
            )
            await phase.call(
                prepared.runtime.aprepare_target_deletion,
                phase.session,
                receipts=prepared.receipts,
                operation_id=row.operation_id,
                operation_type=command.operation,
                actor=request.actor,
            )
            receipts = (
                await phase.call(
                    prepared.runtime.verifier.averify_owner_targets, phase.session, prepared.inspection.targets
                )
                if prepared.inspection.targets
                else ()
            )
            metadata = execution_frame(command.operation, force=command.force)
            metadata["reserved_target_revisions"] = {
                f"model:{receipt.target.key.target_id}": receipt.target.target_revision for receipt in receipts
            }
            metadata["sharing"] = prepared_sharing.metadata() if prepared_sharing is not None else None
            await phase.call(self.providers.abind, phase.session, row, server_id=command.server_id, metadata=metadata)
            preparation = await phase.call(
                self.providers.aread_plan,
                phase.session,
                confirmation_id=operation.preparation.confirmation_id,
                lock=True,
            )
            operation.preparation.check(preparation)
            released = copied_metadata(preparation)
            released["ack"] = {"status": "handoff", "confirmation_id": row.id, "operation_id": row.operation_id}
            await phase.call(
                self.providers.aset_state,
                phase.session,
                row=preparation,
                expected="PREPARING",
                target="COMPLETED",
                metadata=released,
            )
            binding = ModelProjectionBinding.from_plan(row, self.providers) if prepared_sharing is not None else None
            return deepcopy(row), binding

    async def _finish(self, request, command, execution, sharing, prepared_sharing, merged_config):
        async with model_write_phase(self.session_factory, request) as phase:
            await phase.call(self.providers.alock_provider, phase.session, server_id=command.server_id)
            row = await phase.call(self.providers.aread_plan, phase.session, confirmation_id=execution.id)
            self._check_command(row, command, self.providers, request)
            metadata = execution_metadata(row)
            if metadata["force"] != command.force:
                raise KnowledgeOperationPlanChangedError()
            await phase.call(
                self.providers.arequire_idle,
                phase.session,
                server_id=command.server_id,
                allowed_operation_id=row.operation_id,
            )
            prepared = await self._inspect(phase, command, execution=row)
            self._match_inspection(row, command, prepared.inspection, reserved=True)
            self._require_mode(command, prepared.inspection)
            row = await phase.call(self.providers.aread_plan, phase.session, confirmation_id=row.id, lock=True)
            if prepared_sharing is not None:
                await phase.call(sharing.arequire_finalized, phase.session, prepared_sharing)
            removed = tuple(int(key.target_id) for key in prepared.inspection.targets)
            if command.operation == "model_delete_server":
                await phase.call(
                    self.writer.adelete_server, phase.session, server_id=command.server_id, model_ids=removed
                )
                info, new_models, result_digest = None, (), None
            else:
                new_models = await phase.call(
                    self.writer.aupdate_server,
                    phase.session,
                    server=command.server,
                    merged_config=merged_config,
                    removed_model_ids=removed,
                    actor_user_id=request.actor.subject_id,
                )
                provider, models = await phase.call(
                    self.writer.aread_result, phase.session, server_id=command.server_id
                )
                if {model.id for model in models} != set(command.retained) | set(new_models):
                    raise KnowledgeOperationPlanChangedError()
                if set(new_models) & set(removed):
                    raise KnowledgeOperationPlanChangedError()
                result_digest = self.writer.result_digest(provider, models)
                info = LLMServerInfo(
                    **provider.model_dump(),
                    models=[LLMModelInfo(**model.model_dump()) for model in models],
                    share_to_children=bool(prepared_sharing.after) if prepared_sharing is not None else False,
                )
                if request.tenant_id == 1:
                    info.tenant_name = await phase.call(self.writer.aread_owner_name, phase.session)
            await phase.call(
                prepared.runtime.afinalize_target_deletion,
                phase.session,
                receipts=prepared.receipts,
                operation_id=row.operation_id,
                operation_type=command.operation,
                actor=request.actor,
            )
            final_metadata = deepcopy(metadata)
            final_metadata["ack"] = {
                "operation_id": row.operation_id,
                "server_id": command.server_id,
                "removed_model_ids": list(removed),
                "deleted_server": command.operation == "model_delete_server",
                "new_model_ids": list(new_models),
                "result_digest": result_digest,
            }
            await phase.call(
                self.providers.aset_state,
                phase.session,
                row=row,
                expected=row.model_execution_state,
                target="COMPLETED",
                metadata=final_metadata,
            )
            return final_metadata["ack"], info

    async def _run(self, identity, command):
        progress = {"preparation": None, "handoff": False}
        async with model_deletion_request(identity, references=self.references, plans=self.plans) as request:
            try:
                operation = await self._discover(request, command, progress)
                if operation.execution is not None and operation.execution.model_execution_state == "COMPLETED":
                    return await completed_model_result(self, request, command, operation.execution)
                if operation.execution is None:
                    merged_config = None
                    if command.server is not None:
                        from bisheng.llm.domain.services.llm import LLMService
                        from bisheng.utils.mask_data import JsonFieldMasker

                        merged_config = LLMService.strip_config_whitespace(
                            JsonFieldMasker().update_json_with_masked(
                                operation.old_server.config, command.server.config
                            )
                        )
                        await request.call(
                            LLMService._ensure_volcengine_speech,
                            command.server.type,
                            merged_config,
                            command.server.models,
                        )
                    sharing, prepared_sharing = await self._prepare_sharing(request, command, operation)
                    execution, binding = await self._handoff(request, command, operation, prepared_sharing)
                    progress["handoff"] = True
                    if sharing is not None:
                        sharing = await self._sharing(request, binding=binding)
                        await request.call(sharing.arequire_before, prepared_sharing)
                else:
                    progress["handoff"] = True
                    execution = operation.execution
                    metadata = execution_metadata(execution)
                    if metadata["sharing"] is not None:
                        sharing = await self._sharing(request, binding=operation.binding)
                        prepared_sharing = await request.call(
                            sharing.arestore,
                            metadata["sharing"],
                            confirmation_id=execution.id,
                            tenant_id=execution.tenant_id,
                            operation=execution.operation,
                            operator_id=execution.actor_user_id,
                        )
                    else:
                        sharing, prepared_sharing = None, None
                    merged_config = None
                    if command.server is not None:
                        from bisheng.llm.domain.services.llm import LLMService
                        from bisheng.utils.mask_data import JsonFieldMasker

                        async with model_write_phase(self.session_factory, request) as phase:
                            provider = await phase.call(
                                self.providers.alock_provider, phase.session, server_id=command.server_id
                            )
                            merged_config = LLMService.strip_config_whitespace(
                                JsonFieldMasker().update_json_with_masked(provider.config, command.server.config)
                            )
                if prepared_sharing is not None:
                    await request.call(sharing.aexecute, prepared_sharing)
                ack, info = await self._finish(request, command, execution, sharing, prepared_sharing, merged_config)
                from bisheng.llm.domain.utils import invalidate_llm_info_cache

                invalidate_llm_info_cache(server_id=command.server_id)
                for model_id in (*ack["removed_model_ids"], *ack["new_model_ids"], *command.retained):
                    invalidate_llm_info_cache(model_id=model_id)
                from bisheng.llm.domain.services.context_window import ContextWindowService

                await request.call(
                    ContextWindowService.invalidate,
                    [*ack["removed_model_ids"], *ack["new_model_ids"], *command.retained],
                )
                if self.after_update is not None and info is not None:
                    await request.call(
                        self.after_update,
                        request.identity,
                        info,
                        operation.old_server,
                        operation.old_models,
                        command.server,
                    )
                if self.after_delete is not None and info is None:
                    await request.call(self.after_delete, request.identity, operation.old_server)
                return info if info is not None else ack
            finally:
                if progress["preparation"] is not None and not progress["handoff"]:
                    await asyncio.shield(
                        release_model_preparation(
                            progress["preparation"], session_factory=self.session_factory, repository=self.providers
                        )
                    )

    async def aupdate_server(self, *, identity, server, force=False, confirmation_id=None, plan_digest=None):
        return await self._run(
            identity,
            ModelDeleteCommand.create(
                server=server,
                force=force,
                confirmation_id=confirmation_id,
                plan_digest=plan_digest,
            ),
        )

    async def adelete_server(self, *, identity, server_id, force=False, confirmation_id=None, plan_digest=None):
        return await self._run(
            identity,
            ModelDeleteCommand.create(
                server_id=server_id,
                force=force,
                confirmation_id=confirmation_id,
                plan_digest=plan_digest,
            ),
        )


async def get_model_deletion_application():
    from bisheng.llm.domain.services.llm import LLMService

    return ModelDeletionApplication(
        after_delete=LLMService._after_protected_server_delete,
        after_update=LLMService._after_protected_server_update,
    )
