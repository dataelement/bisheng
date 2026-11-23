"""Confirmed knowledge deletion: original projection, native cutover, durable purge."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
from types import SimpleNamespace

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application import deletion_admission as admission
from bisheng.knowledge.domain.models.knowledge_space_delete_job import DELETE_STEPS
from bisheng.knowledge.domain.repositories.knowledge_deletion_execution_repository import (
    KnowledgeDeletionExecutionRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_delete_repository import KnowledgeSpaceDeleteRepository
from bisheng.knowledge.domain.repositories.operation_plan_repository import OperationPlanRepository
from bisheng.knowledge.domain.repositories.processing_fence_repository import ProcessingFenceRepository
from bisheng.knowledge.domain.repositories.source_move_input_repository import SourceMoveInputRepository
from bisheng.knowledge.domain.repositories.space_delete_scope_repository import SpaceDeleteScopeRepository
from bisheng.knowledge.domain.schemas.direct_delete_scope import DeleteSelection, deletion_scope_payload
from bisheng.knowledge.domain.schemas.direct_delete_scope import select_delete_scope as _selected
from bisheng.knowledge.domain.schemas.processing_job import (
    ProcessingCreateRequest,
)
from bisheng.knowledge.domain.services.knowledge_processing_guard import require_space_deletion_allowed
from bisheng.knowledge.domain.services.knowledge_reference_service import KnowledgeReferenceService, impact_digest
from bisheng.permission.application.access import get_f048_resource_adapter, get_f048_runtime
from bisheng.permission.application.business_authorization import (
    PermissionActor,
    VerifiedPermissionTarget,
    batch_check_business_actions,
    require_business_action,
)
from bisheng.permission.application.deleted_resource_cleanup import DeletedResourceCleanup
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.permission.application.knowledge_delete_projection import (
    DeleteProjectionExpectation,
    KnowledgeDeleteProjectionRepository,
    delete_key,
)
from bisheng.resource_reference.application.contracts import (
    TransactionIdentity,
)
from bisheng.resource_reference.application.source_sync import notify_reference_sync


def get_deletion_application():
    return KnowledgeDeletionApplication()


def _selections(values):
    return tuple(DeleteSelection(row["resource_type"], row["resource_id"]) for row in values)


class KnowledgeDeletionApplication:
    def __init__(
        self,
        *,
        session_factory=get_async_db_session,
        coverage_factory=None,
        runtime=None,
        reference_service=None,
        purge_step=None,
        permission_cleanup=None,
    ):
        self.sessions, self.coverage_factory, self.runtime = session_factory, coverage_factory, runtime
        self.references = reference_service or KnowledgeReferenceService(
            session_factory=session_factory, coverage_factory=coverage_factory, runtime=runtime
        )
        self.execution, self.plans = KnowledgeDeletionExecutionRepository(), OperationPlanRepository()
        self.proofs = KnowledgeDeleteProjectionRepository()
        self.purge_step = purge_step
        self.permission_cleanup = permission_cleanup or self._cleanup_permission

    async def _cleanup_permission(self, *, actor, target, delete_idempotency_key):
        await DeletedResourceCleanup(await get_f048_runtime(), session_factory=self.sessions).run(
            actor=actor, target=target, delete_idempotency_key=delete_idempotency_key
        )

    @staticmethod
    def _quiescent(session):
        if session.new or session.dirty or session.deleted:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_pending_tail")

    @asynccontextmanager
    async def _session(self):
        tenant = admission.tenant()
        async with self.sessions() as session:
            if not isinstance(session, AsyncSession) or session.in_transaction():
                raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_fresh_session_required")
            self._quiescent(session)
            async with session.begin():
                transaction = TransactionIdentity.capture(session)
                yield session
                transaction.assert_current(session)
                self._quiescent(session)
                if admission.tenant() != tenant:
                    raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_context_changed")

    @asynccontextmanager
    async def _savepoint(self, session):
        self._quiescent(session)
        async with session.begin_nested():
            yield
            self._quiescent(session)

    async def _collect(self, session, *, space_id, selections, operation, operation_id=None):
        if operation != "knowledge_file_delete":
            scope = await SpaceDeleteScopeRepository().aread_space_scope(session, space_id=space_id, for_update=True)
        else:
            scope = await KnowledgeSpaceDeleteRepository().aread_delete_scope(
                session, space_id=space_id, selections=selections, for_update=True
            )
        return SimpleNamespace(scope=scope)

    async def _permissions(self, identity, scope):
        actor, tenant = get_current_permission_actor(), admission.tenant()
        allowed = set()
        for kind in ("folder", "knowledge_file"):
            ids = [row.id for row in scope.resources if (row.file_type == 0) == (kind == "folder")]
            for offset in range(0, len(ids), 200):
                page = tuple(ids[offset : offset + 200])
                values = await batch_check_business_actions(
                    identity, resource_type=kind, resource_ids=page, actions=("delete",)
                )
                if admission.tenant() != tenant or get_current_permission_actor() is not actor:
                    raise ResourceReferenceInvalidError(reason="knowledge_delete_actor_changed")
                allowed.update(ident for ident in page if "delete" in values.get(str(ident), ()))
        return allowed

    async def _pin(self):
        runtime = await get_f048_runtime()
        current = await runtime.current_catalog()
        return {
            name: getattr(current, name)
            for name in ("release_id", "release_key", "checksum", "store_id", "model_id", "model_checksum")
        }

    async def _targets(self, scope, operation):
        actor, tenant = get_current_permission_actor(), admission.tenant()
        resources = [("folder" if row.file_type == 0 else "knowledge_file", row.id) for row in scope.resources]
        if operation == "knowledge_space_delete":
            resources.append(("knowledge_space", scope.space_id))
        targets = []
        for kind, ident in resources:
            adapter = await get_f048_resource_adapter(kind)
            record = await adapter.load_permission_record(resource_type=kind, resource_id=str(ident))
            if record is None or (record.tenant_id, record.resource_type, record.resource_id) != (
                tenant,
                kind,
                str(ident),
            ):
                raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_permission_snapshot_missing")
            targets.append(adapter._lifecycle_target(record, actor, kind, str(ident)).model_dump(mode="json"))
            if admission.tenant() != tenant or get_current_permission_actor() is not actor:
                raise ResourceReferenceInvalidError(reason="knowledge_delete_actor_changed")
        return targets

    async def aprecheck(self, **kwargs):
        from bisheng.knowledge.application.knowledge_delete_precheck import precheck_deletion

        return await precheck_deletion(self, **kwargs)

    async def ainspect_selections(self, *, identity, space_id, selections):
        reference = await admission.capture(identity, space_id=space_id)
        async with admission.identity(reference, current=identity) as (actual, _):
            permitted = await admission.selected_positions(actual, selections)
            return {"permitted_selection_count": len(permitted)}

    async def aordinary_delete(
        self, *, identity, space_id, selections=(), operation="knowledge_file_delete", historical_version_id=None
    ):
        review = await self.aprecheck(
            identity=identity,
            space_id=space_id,
            selections=selections,
            operation=operation,
            historical_version_id=historical_version_id,
        )
        if not review.can_execute or review.invalid_items:
            if review.invalid_items and all(row.reason == "no_permission" for row in review.invalid_items):
                raise PermissionDeniedError()
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_explicit_review_required")
        await self.aconfirm(
            identity=identity,
            space_id=space_id,
            request=ProcessingCreateRequest(
                confirmation_id=review.confirmation_id,
                plan_digest=review.plan_digest,
                idempotency_key=f"delete:{review.confirmation_id}",
            ),
        )
        async with self._session() as session:
            job = await self.execution.aget(session, review.confirmation_id)
            return {
                key: value
                for key, value in job.manifest.items()
                if key not in {"execution", "continuation", "projection_targets"}
            }

    async def adelete_historical_version(self, *, identity, version_id):
        async with self._session() as session:
            row = await self.execution.aresolve_historical_version(session, version_id=version_id)
        if row is None or row["is_primary"]:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_non_primary_version_required")
        await self.aordinary_delete(
            identity=identity,
            space_id=row["knowledge_id"],
            selections=(DeleteSelection("knowledge_file", row["file_id"]),),
            historical_version_id=version_id,
        )
        return {
            "document_id": row["document_id"],
            "deleted_version_no": row["version_no"],
            "knowledge_id": row["knowledge_id"],
            "file_name": row["file_name"],
        }

    async def astatus(self, *, identity, space_id, job_id):
        async with self._session() as session:
            plan = await self.execution.apeek_plan(session, job_id)
        if plan.space_id != space_id:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_scope_mismatch")
        async with admission.identity(plan.actor_reference, current=identity):
            async with self._session() as session:
                job = await self.execution.aget(session, job_id)
                if job is None or job.operation_type != plan.operation:
                    raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_job_missing")
                return {
                    "job_id": job.id,
                    "state": job.state.lower(),
                    "business_phase": job.business_phase,
                    "completed_steps": job.completed_steps,
                }

    async def acompletion_details(self, *, identity, space_id, request, completed=False):
        """Internal original-business hooks; never serialize the cleanup manifest."""
        async with self._session() as session:
            plan = await self.execution.apeek_plan(session, request.confirmation_id)
        if plan.space_id != space_id or plan.plan_digest != request.plan_digest:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_confirmation_changed")
        async with admission.identity(plan.actor_reference, current=identity):
            if not completed:
                return plan.operation, None
            async with self._session() as session:
                job = await self.execution.aget(session, plan.id)
                if job is None or job.manifest["execution"]["idempotency_key"] != request.idempotency_key:
                    raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_idempotency_changed")
                await self.execution.arequire_completed(session, job=job, plan=plan)
                return plan.operation, self._cleanup_details(job)

    @staticmethod
    def _cleanup_details(job):
        return {
            key: value
            for key, value in job.manifest.items()
            if key not in {"execution", "continuation", "projection_targets"}
        }

    async def _locked(self, session, plan, *, operation_id=None, manifest=None):
        values = plan.parameters
        selections = (
            _selections(values["selections"]) if manifest is None else _selections(manifest["execution"]["selections"])
        )
        facts_holder = {}

        async def root_lock(active):
            root, checksum = await self.execution.aroot(active, plan.space_id, lock=True)
            if checksum != plan.source_revisions["root"]:
                raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_root_changed")
            require_space_deletion_allowed(root, operation=plan.operation)
            await self.execution.arequire_transfer_idle(active, space_id=plan.space_id)
            await SourceMoveInputRepository().arequire_released(active, space_id=plan.space_id)
            facts_holder["facts"] = await self._collect(
                active,
                space_id=plan.space_id,
                selections=selections,
                operation=plan.operation,
                operation_id=operation_id,
            )
            facts_holder["root"] = root
            return root

        await root_lock(session)
        facts = facts_holder["facts"]
        scope = facts.scope if manifest is not None else _selected(facts.scope, tuple(values["valid_positions"]))
        expected_scope = plan.target_revisions["scope"] if manifest is None else manifest["execution"]["scope_digest"]
        if (
            impact_digest(
                deletion_scope_payload(facts.scope)
                if values.get("processing_fence_version") == 1
                else asdict(facts.scope)
            )
            != expected_scope
        ):
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_impact_changed")
        return facts_holder["root"], facts, scope, None

    async def aconfirm(self, *, identity, space_id, request: ProcessingCreateRequest):
        async with self._session() as session:
            plan = await self.execution.apeek_plan(session, request.confirmation_id)
        if plan.space_id != space_id or plan.plan_digest != request.plan_digest:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_confirmation_changed")
        if not plan.parameters["can_execute"]:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_no_executable_scope")
        async with admission.identity(plan.actor_reference, current=identity) as (actual, continuation):
            if plan.operation_id is not None:
                async with self._session() as session:
                    job = await self.execution.aget(session, plan.id)
                    if job is None or job.manifest["execution"]["idempotency_key"] != request.idempotency_key:
                        raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_idempotency_changed")
                    self.execution.validate_job(job, plan)
                    if job.state == "SUCCEEDED":
                        await self.execution.arequire_completed(session, job=job, plan=plan)
                        return {"job_id": job.id, "state": "succeeded", "accepted": False, "reused": True}
                    await self.execution.arefresh_continuation(session, job_id=job.id, reference=continuation)
            else:
                if plan.operation == "knowledge_file_delete":
                    requested = _selections(plan.parameters.get("requested_selections", plan.parameters["selections"]))
                    expected = tuple(plan.parameters.get("authorized_positions", range(len(requested))))
                    if await admission.selected_positions(actual, requested) != expected:
                        raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_permissions_changed")
                async with self._session() as session:
                    current = await self._collect(
                        session,
                        space_id=space_id,
                        selections=_selections(plan.parameters["selections"]),
                        operation=plan.operation,
                    )
                chosen = _selected(current.scope, tuple(plan.parameters["valid_positions"]))
                if plan.operation == "knowledge_file_delete" and not chosen.resources:
                    raise ResourceReferenceInvalidError(reason="knowledge_delete_no_valid_items")
                if plan.operation == "knowledge_file_delete" and not {
                    row.id for row in chosen.resources
                } <= await self._permissions(actual, chosen):
                    raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_permissions_changed")
                targets = await self._targets(chosen, plan.operation)
                if await self._pin() != plan.parameters["pin"]:
                    raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_catalog_changed")
                async with self._session() as session:
                    async with self._savepoint(session):
                        root, _facts, scope, _ = await self._locked(session, plan)
                        locked = await self.plans.aget_for_execution(
                            session,
                            plan.id,
                            space_id=space_id,
                            operation=plan.operation,
                            actor_reference=plan.actor_reference,
                            plan_digest=request.plan_digest,
                        )
                        if locked.operation_id is not None:
                            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_concurrent_confirmation")
                        verified = tuple(VerifiedPermissionTarget.from_business_service(**row) for row in targets)
                        for start in range(0, max(1, len(verified)), 200):
                            await self.proofs.arequire_current(
                                session, targets=verified[start : start + 200], pin=plan.parameters["pin"]
                            )
                        await self.plans.aconsume(
                            session, plan.id, operation_id=plan.id, expected_digest=request.plan_digest
                        )
                        manifest = self.execution.cleanup_manifest(scope)
                        manifest.update(
                            {
                                "queued_files": [
                                    {"file_id": row.id, "user_id": row.user_id}
                                    for row in scope.resources
                                    if row.file_type == 1
                                ],
                                "cancel_processing": root.state == 3
                                or root.model_transition is not None
                                or any(unit.processing_file_ids for unit in scope.units),
                                "projection_targets": targets,
                                "continuation": continuation,
                                "execution": {
                                    "confirmation_id": plan.id,
                                    "plan_digest": plan.plan_digest,
                                    "idempotency_key": request.idempotency_key,
                                    "actor_reference": plan.actor_reference,
                                    "selections": [asdict(row) for row in scope.selections],
                                    "scope_digest": impact_digest(deletion_scope_payload(scope)),
                                    "inbound_digest": impact_digest([]),
                                },
                            }
                        )
                        # The marker and task cancellation share the confirmation transaction.
                        cancelled = await self.execution.acancel_processing(session, plan=locked, scope=scope)
                        manifest["cancel_processing"] = manifest["cancel_processing"] or cancelled
                        await self.execution.acreate(session, plan=locked, manifest=manifest)
        from bisheng.knowledge.domain.services.knowledge_space_direct_delete_service import (
            KnowledgeSpaceDirectDeleteService,
        )

        service = KnowledgeSpaceDirectDeleteService(
            session_factory=self.sessions, execution_application_factory=lambda: self, purge_step=self.purge_step
        )
        # Parsing/rebuild deletion returns promptly; cleanup waits for actual
        # writer transactions in the worker, never in this request.
        async with self._session() as session:
            job = await self.execution.aget(session, plan.id)
        asynchronous = job.manifest.get("cancel_processing", False)
        if asynchronous:
            try:
                await service.dispatch(tenant_id=job.tenant_id, job_id=job.id)
            except Exception:
                logger.exception("Deletion accepted; periodic dispatch will recover job={}", job.id)
        else:
            await service.purge(plan.id)
        async with self._session() as session:
            job = await self.execution.aget(session, plan.id)
            return {"job_id": job.id, "state": job.state.lower(), "accepted": job.state != "SUCCEEDED"}

    async def _finalize(self, job):
        async with admission.identity(
            job.manifest["execution"]["actor_reference"], continuation=job.manifest["continuation"]
        ) as (actual, _):
            if job.operation_type == "knowledge_space_clear":
                # Clear preserves the Root permission projection, so its actual
                # delete decision remains available for the final admission.
                await require_business_action(
                    actual, resource_type="knowledge_space", resource_id=job.space_id, action="delete"
                )
            targets = tuple(
                VerifiedPermissionTarget.from_business_service(**row) for row in job.manifest["projection_targets"]
            )
            await admission.narrow(tuple((row.resource_type, row.resource_id) for row in targets))
            async with self._session() as session:
                async with self._savepoint(session):
                    plan = await self.execution.apeek_plan(session, job.id)
                    root, _, scope, _binding = await self._locked(
                        session, plan, operation_id=job.id, manifest=job.manifest
                    )
                    current = await self.execution.aget(session, job.id, lock=True)
                    if (
                        current is None
                        or current.lease_token != job.lease_token
                        or current.manifest != job.manifest
                        or current.business_phase != "prepared"
                        or current.completed_steps != ["fga"]
                    ):
                        raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_lease_changed")
                    locked_plan = await self.plans._locked(session, job.id)
                    if (
                        locked_plan.model_dump() != plan.model_dump()
                        or job.manifest["execution"]["actor_reference"] != plan.actor_reference
                        or job.manifest["execution"]["plan_digest"] != plan.plan_digest
                    ):
                        raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_execution_plan_changed")
                    refreshed = self.execution.cleanup_manifest(scope)
                    if any(refreshed[key] != job.manifest[key] for key in refreshed if key != "object_names"):
                        raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_manifest_changed")
                    # Keep the original frozen manifest. Newly generated keys
                    # are also collected from the crash-safe output inventory.
                    actor = get_current_permission_actor()
                    expected = tuple(DeleteProjectionExpectation(job.id, row, actor.user_id) for row in targets)
                    for start in range(0, max(1, len(expected)), 200):
                        await self.proofs.arequire_finalized(
                            session, expectations=expected[start : start + 200], pin=plan.parameters["pin"]
                        )
                    await self.execution.afinalize_scope(session, scope=scope)
                    if plan.operation == "knowledge_space_delete":
                        await self.execution.acleanup_deleted_space(session, space_id=plan.space_id)
                        await session.delete(root)
                        await session.flush()
                    await self.execution.amark_finalized(session, job=current)
            await notify_reference_sync(admission.tenant(), "knowledge", str(plan.space_id))
            job.business_phase = "finalized"

    async def apurge_claimed(self, job, *, repository, purge_step):
        try:
            fence = ProcessingFenceRepository(async_sessions=self.sessions)
            async with fence.cleanup(job):
                return await self._purge_quiescent(job, repository=repository, purge_step=purge_step)
        except BaseException as error:
            try:
                await repository.advance(job, error=type(error).__name__)
            except BaseException:
                logger.opt(exception=True).warning(
                    "Knowledge deletion failure checkpoint could not be acknowledged job={}", job.id
                )
            raise

    async def _purge_quiescent(self, job, *, repository, purge_step):
        if job.manifest.get("cancel_processing"):
            from bisheng.worker.knowledge.scheduler import FileScheduler

            scheduler = FileScheduler()
            for row in job.manifest.get("queued_files", ()):
                await asyncio.to_thread(scheduler.purge_file, user_id=str(row["user_id"]), file_id=str(row["file_id"]))
        async with self._session() as session:
            plan = await self.execution.apeek_plan(session, job.id)
            self.execution.validate_job(job, plan)
        if "fga" not in job.completed_steps:
            for raw in job.manifest["projection_targets"]:
                await repository.advance(job)
                async with admission.identity(
                    job.manifest["execution"]["actor_reference"], continuation=job.manifest["continuation"]
                ):
                    target = VerifiedPermissionTarget.from_business_service(**raw)
                    await admission.narrow(((target.resource_type, target.resource_id),))
                    await (await get_f048_runtime()).project_delete(
                        actor=get_current_permission_actor(),
                        target=target,
                        idempotency_key=delete_key(job.id, target),
                    )
            await repository.advance(job, step="fga")
        if job.business_phase == "prepared":
            await self._finalize(job)
        if job.business_phase != "finalized":
            raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_phase_invalid")
        # The business transaction above still needs the original mode and
        # RESOURCE_DELETE receipt. Purge mirrors only after that cutover.
        for raw in job.manifest["projection_targets"]:
            await repository.advance(job)
            target = VerifiedPermissionTarget.from_business_service(**raw)
            # This is receipt-bound deletion cleanup, like physical purge.
            # Personal ownership was checked before cutover: the deleted
            # row cannot now satisfy a fresh live filter_owned query.
            await self.permission_cleanup(
                actor=PermissionActor(user_id=job.applicant_user_id, current_tenant_id=job.tenant_id),
                target=target,
                delete_idempotency_key=delete_key(job.id, target),
            )
        for step in DELETE_STEPS[1:]:
            if step not in job.completed_steps:
                await repository.advance(job)
                await purge_step(step, job)
                await repository.advance(job, step=step)
        await repository.advance(job, complete=True)
        return True
