"""Serialize the original Root provider sharing writers with model deletion."""

import asyncio
from copy import deepcopy

from loguru import logger

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeProcessingConflictError
from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao
from bisheng.llm.application.model_deletion_context import execution_frame, model_deletion_request, model_write_phase
from bisheng.llm.application.model_operation_recovery import (
    ModelSharingPreparation,
    abandon_unstarted,
    needs_recovery,
    release_failed_sharing,
)
from bisheng.llm.application.model_provider_projection import (
    ModelProjectionBinding,
    ModelProviderProjectionScope,
    execution_metadata,
)
from bisheng.llm.domain.repositories.model_delete_plan_repository import ModelDeletePlanRepository, _hash
from bisheng.llm.domain.repositories.model_deletion_repository import _revision
from bisheng.llm.domain.repositories.model_provider_operation_repository import ModelProviderOperationRepository
from bisheng.llm.domain.repositories.model_sharing_intent_repository import ModelSharingIntentRepository
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
        self.intents = ModelSharingIntentRepository()
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

    async def aprepare_cancellation(self, *, identity, server_id, expected_fingerprint=None):
        """Preview or explicitly abandon a preparation that never started I/O."""
        if type(server_id) is not int or server_id <= 0:
            raise KnowledgeOperationPlanChangedError()
        async with model_deletion_request(identity, references=self.references, plans=self.plans) as request:
            if request.tenant_id != ROOT_TENANT_ID or not request.actor.super_admin:
                raise LLMModelNotAccessibleError()
            sharing = await self._permission(request)
            async with model_write_phase(self.session_factory, request) as phase:
                await phase.call(self.providers.alock_provider, phase.session, server_id=server_id)
                row = await phase.call(self.providers.aactive_plan, phase.session, server_id=server_id)
                if row is None:
                    raise KnowledgeOperationPlanChangedError()
                self.providers.require_unstarted_preparation(row)
                if execution_metadata(row) != execution_frame("model_share_server"):
                    raise KnowledgeOperationPlanChangedError()
                receipt = await phase.call(self.intents.aread_initialization, phase.session, plan_id=row.id)
                if receipt is not None:
                    raise KnowledgeOperationPlanChangedError()
                await phase.call(
                    sharing.arequire_unstarted,
                    phase.session,
                    server_id=server_id,
                    confirmation_id=row.id,
                )
                fingerprint = self.providers.preparation_fingerprint(row)
                if expected_fingerprint is not None:
                    if expected_fingerprint != fingerprint:
                        raise KnowledgeOperationPlanChangedError()
                    metadata = deepcopy(row.model_execution_metadata)
                    metadata["ack"] = {
                        "status": "abandoned_unstarted",
                        "cancel_actor_user_id": request.actor.subject_id,
                        "original_fingerprint": fingerprint,
                    }
                    await phase.call(
                        self.providers.aset_state,
                        phase.session,
                        row=row,
                        expected="PREPARING",
                        target="ABANDONED",
                        metadata=metadata,
                    )
                return {"plan_id": row.id, "fingerprint": fingerprint, "abandoned": expected_fingerprint is not None}

    async def _recover_previous(self, request, *, server_id):
        async with model_write_phase(self.session_factory, request) as phase:
            row = await phase.call(self.providers.aactive_plan, phase.session, server_id=server_id)
            if row is None:
                return
            await phase.call(self.providers.alock_provider, phase.session, server_id=server_id)
            row = await phase.call(self.providers.aactive_plan, phase.session, server_id=server_id)
            if row is None or not needs_recovery(row, self.plans.clock()):
                return
            if await phase.call(
                abandon_unstarted,
                phase.session,
                providers=self.providers,
                row=row,
                actor_user_id=request.actor.subject_id,
            ):
                return
            metadata = execution_metadata(row)
            if row.operation != "model_share_server" or metadata["purpose"] != "model_share_server":
                return
            if request.tenant_id != ROOT_TENANT_ID or not request.actor.super_admin:
                raise LLMModelNotAccessibleError()
            self.providers.validate(row)
            saved = deepcopy(row)
            binding = ModelProjectionBinding.from_plan(row, self.providers)
        sharing = await self._permission(request, binding)
        prepared = await request.call(
            sharing.arestore,
            execution_metadata(saved)["sharing"],
            confirmation_id=saved.id,
            tenant_id=saved.tenant_id,
            operation=saved.operation,
            operator_id=saved.actor_user_id,
        )
        await request.call(sharing.aexecute, prepared)
        # Sharing commands store only their digest, never provider credentials.
        # Explicit ON/OFF is identifiable; child/mount commands retain the switch.
        intent_enabled = None
        for value in (False, True):
            if saved.parameters["command_digest"] == _hash(
                {"operation": "model_share_server", "server_id": server_id, "enabled": value, "child_id": None}
            ):
                intent_enabled = value
                break
        await self._finish_sharing(
            request,
            saved,
            prepared,
            sharing,
            binding,
            server_id=server_id,
            intent_enabled=intent_enabled,
            recovery=True,
        )
        return saved.parameters["command_digest"], prepared

    async def arecover_before_write(self, *, identity, server_id):
        """Recover a failed previous command before admitting a new provider PUT."""
        async with model_deletion_request(identity, references=self.references, plans=self.plans) as request:
            if request.tenant_id != ROOT_TENANT_ID or not request.actor.super_admin:
                raise LLMModelNotAccessibleError()
            await self._recover_previous(request, server_id=server_id)
            async with model_write_phase(self.session_factory, request) as phase:
                await phase.call(self.providers.alock_provider, phase.session, server_id=server_id)
                await phase.call(self.providers.arequire_idle, phase.session, server_id=server_id)

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

    async def arepair_enabled_sharing(
        self, *, identity, server_id, expected_enabled, expected_version, expected_plan_id, adopt_only=False
    ):
        """Conditionally reconcile an enabled switch; never overwrite a newer OFF.

        Adoption records legacy intent without adding recipients. The additive
        model writer can then reference a real completed initialization plan.
        """
        if (
            type(server_id) is not int
            or server_id <= 0
            or expected_enabled not in (None, True)
            or (expected_enabled is not None and type(expected_enabled) is not bool)
            or type(expected_version) is not int
            or expected_version < 0
            or (expected_plan_id is not None and (type(expected_plan_id) is not str or len(expected_plan_id) != 36))
            or ((expected_enabled is None) != (expected_version == 0 and expected_plan_id is None))
            or (expected_enabled is True and expected_plan_id is None)
            or type(adopt_only) is not bool
        ):
            raise KnowledgeOperationPlanChangedError()
        pin = (expected_enabled, expected_version, expected_plan_id)
        command = _hash(
            {
                "operation": "model_share_server",
                "server_id": server_id,
                "enabled": True,
                "child_id": None,
                "expected_intent": pin,
                "adopt_only": adopt_only,
            }
        )
        return await self._set_sharing(
            identity=identity,
            server_id=server_id,
            enabled=True,
            child_id=None,
            command=command,
            expected_intent=pin,
            adopt_only=adopt_only,
        )

    async def _set_sharing(
        self, *, identity, server_id, enabled, child_id, command, mounted=None, expected_intent=None, adopt_only=False
    ):
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
            recovered = await self._recover_previous(request, server_id=server_id)
            if recovered is not None and recovered[0] == command:
                return await self._sharing_result(
                    request, recovered[1], server_id=server_id, enabled=enabled, child_id=child_id
                )
            progress = {"preparation": None}
            try:
                return await self._execute_sharing(
                    request,
                    server_id=server_id,
                    enabled=enabled,
                    child_id=child_id,
                    command=command,
                    mounted=mounted,
                    progress=progress,
                    expected_intent=expected_intent,
                    adopt_only=adopt_only,
                )
            except BaseException:
                if progress["preparation"] is not None:
                    try:
                        await asyncio.shield(
                            release_failed_sharing(
                                progress["preparation"], session_factory=self.session_factory, providers=self.providers
                            )
                        )
                    except Exception:
                        logger.exception(
                            "Could not close failed model sharing operation {}; next edit will recover it",
                            progress["preparation"].confirmation_id,
                        )
                raise

    async def _execute_sharing(
        self, request, *, server_id, enabled, child_id, command, mounted, progress, expected_intent, adopt_only
    ):
        legacy_snapshot = None
        if child_id is not None or expected_intent is not None:
            async with model_write_phase(self.session_factory, request) as phase:
                await phase.call(self.providers.alock_provider, phase.session, server_id=server_id)
                observed_intent = await phase.call(self.intents.aread, phase.session, server_id=server_id)
            if observed_intent is None:
                native = await self._permission(request)
                legacy_snapshot = await request.call(native.aread, server_id=server_id)
        async with model_write_phase(self.session_factory, request) as phase:
            provider = await phase.call(self.providers.alock_provider, phase.session, server_id=server_id)
            await self._check_mounted(phase, mounted)
            if provider.tenant_id != ROOT_TENANT_ID:
                raise LLMModelNotAccessibleError()
            if child_id is not None or expected_intent is not None:
                intent = await phase.call(self.intents.aread, phase.session, server_id=server_id)
                pin = (intent.enabled, intent.version, intent.plan_id) if intent else (None, 0, None)
                if expected_intent is not None and pin != expected_intent:
                    raise KnowledgeOperationPlanChangedError()
                if (intent is not None and not intent.enabled) or (
                    intent is None and (legacy_snapshot is None or not legacy_snapshot.subjects)
                ):
                    raise KnowledgeOperationPlanChangedError()
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
                raise KnowledgeProcessingConflictError(reason="model_provider_operation_active")
            saved = deepcopy(row)
            progress["preparation"] = ModelSharingPreparation.from_plan(row)
        sharing = await self._permission(request)
        before = await request.call(sharing.aread, server_id=server_id)
        if adopt_only:
            if not before.subjects:
                raise KnowledgeOperationPlanChangedError()
            after = before.subjects
        elif child_id is not None:
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
        initialization_children = set(prepared.after) - set(prepared.before.subjects)
        if expected_intent is not None and not adopt_only:
            active = await request.call(TenantDao.aget_children_ids_active, ROOT_TENANT_ID)
            initialization_children = set(prepared.after) & set(active)
        async with model_write_phase(self.session_factory, request) as phase:
            await phase.call(self.providers.alock_provider, phase.session, server_id=server_id)
            await self._check_mounted(phase, mounted)
            row = await phase.call(self.providers.aread_plan, phase.session, confirmation_id=saved.id, lock=True)
            if row.operation_id != saved.operation_id or row.model_execution_state != "PREPARING":
                raise KnowledgeOperationPlanChangedError()
            self.providers.require_current_actor(row, request.actor_reference)
            await phase.call(
                self.intents.afreeze_initialization,
                phase.session,
                plan_id=row.id,
                server_id=server_id,
                child_ids=initialization_children,
            )
            metadata = execution_frame("model_share_server")
            metadata["sharing"] = prepared.metadata()
            await phase.call(self.providers.abind, phase.session, row, server_id=server_id, metadata=metadata)
            binding = ModelProjectionBinding.from_plan(row, self.providers)
        sharing = await self._permission(request, binding)
        await request.call(sharing.arequire_before, prepared)
        await request.call(sharing.aexecute, prepared)
        await self._finish_sharing(
            request,
            saved,
            prepared,
            sharing,
            binding,
            server_id=server_id,
            intent_enabled=enabled if child_id is None else None,
            mounted=mounted,
        )
        return await self._sharing_result(request, prepared, server_id=server_id, enabled=enabled, child_id=child_id)

    async def _sharing_result(self, request, prepared, *, server_id, enabled, child_id):
        if not enabled:
            return list(prepared.before.subjects)
        if child_id is not None:
            return [child_id]
        active = await request.call(TenantDao.aget_children_ids_active, ROOT_TENANT_ID)
        return sorted(set(active) & set(prepared.after))

    async def _finish_sharing(
        self, request, saved, prepared, sharing, binding, *, server_id, intent_enabled, mounted=None, recovery=False
    ):
        async with model_write_phase(self.session_factory, request) as phase:
            await phase.call(self.providers.alock_provider, phase.session, server_id=server_id)
            await self._check_mounted(phase, mounted)
            row = await phase.call(self.providers.aread_plan, phase.session, confirmation_id=saved.id, lock=True)
            if not recovery:
                self.providers.require_current_actor(row, request.actor_reference)
            if row.model_execution_state == "COMPLETED" and recovery:
                return
            binding.check_scalar(await phase.call(self.providers.ascalar_pin, phase.session, confirmation_id=row.id))
            await phase.call(sharing.arequire_finalized, phase.session, prepared)
            receipt = await phase.call(self.intents.aread_initialization, phase.session, plan_id=row.id)
            if receipt is not None:
                from bisheng.dsh.domain.services.shared_model_visibility import initialize_shared_model_visibility

                await phase.call(
                    initialize_shared_model_visibility,
                    phase.session,
                    child_ids=receipt.child_ids,
                    model_ids=receipt.model_ids,
                    actor_user_id=row.actor_user_id,
                    plan_id=row.id,
                    guard=request.check,
                )
            if intent_enabled is not None:
                await phase.call(
                    self.intents.aset, phase.session, server_id=server_id, enabled=intent_enabled, plan_id=row.id
                )
            else:
                # A new receiver also advances the producer version. An
                # additive writer that froze recipients before this mount
                # must retry rather than miss this newly received model.
                intent = await phase.call(self.intents.aread, phase.session, server_id=server_id)
                await phase.call(
                    self.intents.aset,
                    phase.session,
                    server_id=server_id,
                    enabled=intent.enabled if intent else True,
                    plan_id=row.id,
                )
            metadata = deepcopy(execution_metadata(row))
            metadata["ack"] = {"status": "shared", "operation_id": row.operation_id}
            if recovery:
                metadata["ack"]["recovered_by"] = request.actor.subject_id
            await phase.call(
                self.providers.aset_state,
                phase.session,
                row=row,
                expected=row.model_execution_state,
                target="COMPLETED",
                metadata=metadata,
            )


async def get_model_sharing_application():
    return ModelSharingApplication()
