"""Knowledge processing use cases in the caller's native SQL transaction.

Assembly supplies executable kinds. An empty assembly refuses submissions.
The caller commits a retry's durable error outcome before raising that error.
"""

from dataclasses import dataclass
from datetime import timedelta

from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge import (
    KnowledgeIdempotencyConflictError,
    KnowledgeOperationConfirmationRequiredError,
    KnowledgeOperationPlanChangedError,
    KnowledgeProcessingConflictError,
    KnowledgeProcessingJobNotFoundError,
    KnowledgeProcessingObsoleteError,
)
from bisheng.common.schemas.api import PageData
from bisheng.knowledge.application.processing_identity import capture_processing_actor
from bisheng.knowledge.domain.repositories.operation_plan_repository import OperationPlanRepository
from bisheng.knowledge.domain.repositories.processing_job_repository import NewProcessingItem
from bisheng.knowledge.domain.repositories.processing_owner_repository import ProcessingOwnerRepository
from bisheng.knowledge.domain.repositories.processing_settings_repository import ProcessingSettingsRepository
from bisheng.knowledge.domain.schemas.processing_job import (
    JobAccepted,
    OperationItem,
    ProcessingCreateRequest,
    ProcessingItemRead,
    ProcessingJobRead,
    ProcessingPrecheckRequest,
    ProcessingRetryRequest,
)
from bisheng.permission.application.business_authorization import batch_check_business_actions, require_business_action


@dataclass(frozen=True, slots=True)
class ProcessingRetryOutcome:
    data: JobAccepted | None = None
    error: BaseErrorCode | None = None


class ProcessingJobService:
    def __init__(self, *, owner, available_kinds=frozenset(), plans=None, scope=None, settings=None):
        self.owner = owner
        self.jobs = owner.jobs
        self.plans = plans if plans is not None else OperationPlanRepository()
        self.scope = scope if scope is not None else ProcessingOwnerRepository()
        self.settings = settings if settings is not None else ProcessingSettingsRepository()
        # File/metadata/move/copy require their own actual handlers and Owners.
        self.available_kinds = frozenset(available_kinds) & {"embedding_rebuild"}

    def _kind(self, kind):
        if kind not in self.available_kinds:
            raise KnowledgeProcessingConflictError(reason="processing_kind_unavailable")

    @staticmethod
    def require_rebuild_scope_ready(scope):
        if any(row.status in {1, 4, 5} for row in scope):
            raise KnowledgeProcessingConflictError(reason="processing_file_state_not_ready")

    @staticmethod
    async def _authorize(identity, space_id):
        await require_business_action(identity, resource_type="knowledge_space", resource_id=space_id, action="edit")

    @staticmethod
    def _versions(preview, scope):
        targets = {
            f"{row.target.file_id}:{row.target.version_id}": {
                "revision": row.revision,
                "original_status": row.status,
                "participates": row.status == 2,
            }
            for row in scope
        }
        targets["models"] = {
            f"{item.target.key.target_type.value}:{item.target.key.target_id}": item.target.target_revision
            for item in preview.bindings.verified.context.receipts
        }
        source = {
            "model_config_revision": preview.expected_revision,
            "index_generation": preview.expected_generation,
            "source_root_revision": preview.bindings.expected_revision,
            "old_references_digest": preview.bindings.verified.context.old_references_digest,
        }
        return targets, source

    async def aprecheck(self, session, space_id, request, *, identity, entry_kind):
        request = ProcessingPrecheckRequest.model_validate(request.model_dump(mode="json"))
        self._kind(request.kind)
        await self._authorize(identity, space_id)
        actor = await capture_processing_actor(
            identity, space_id=space_id, required_action="edit", entry_kind=entry_kind
        )
        parameters = request.parameters.model_dump(mode="json")
        preview = await self.owner.apreview(session, space_id, identity=identity, parameters=parameters)
        scope = await self.scope.aload_scope(session, space_id)
        self.require_rebuild_scope_ready(scope)
        targets, source = self._versions(preview, scope)
        participants = tuple(row for row in scope if row.status == 2)
        skipped_count = len(scope) - len(participants)
        plan = await self.plans.acreate(
            session,
            operation=request.kind,
            space_id=space_id,
            actor_reference=actor.reference,
            targets=[row.target for row in scope],
            target_revisions=targets,
            source_revisions=source,
            parameters=parameters,
            impact={
                "whole_version_count": len(scope),
                "participating_version_count": len(participants),
                "skipped_version_count": skipped_count,
                "retrieval_paused": True,
                "preserves_chunks": True,
            },
            expires_at=self.plans.clock() + timedelta(minutes=5),
        )
        # A whole-space command confirms its container/count. Hidden file IDs
        # and names remain only in the private persisted target manifest.
        return plan.model_copy(
            update={
                "can_execute": bool(participants),
                "valid_items": [OperationItem(id=space_id, type="space")] if participants else [],
                "requires_skip_confirmation": bool(skipped_count),
            }
        )

    @staticmethod
    def _accepted(result):
        return JobAccepted(job_id=result.job.id, state=result.job.state, reused=result.reused)

    async def acreate(self, session, space_id, request, *, identity, entry_kind):
        request = ProcessingCreateRequest.model_validate(request.model_dump(mode="json"))
        await self._authorize(identity, space_id)
        actor = await capture_processing_actor(
            identity, space_id=space_id, required_action="edit", entry_kind=entry_kind
        )
        candidate = await self.plans._locked(session, request.confirmation_id)
        self._kind(candidate.operation)
        plan = await self.plans.aget_for_execution(
            session,
            request.confirmation_id,
            space_id=space_id,
            operation=candidate.operation,
            actor_reference=actor.reference,
            plan_digest=request.plan_digest,
        )
        existing = await self.jobs.aget_by_request_key(session, plan.operation, request.idempotency_key)
        if existing is not None:
            if (
                existing.space_id != space_id
                or existing.actor_reference != actor.reference
                or existing.parameters.get("confirmation_id") != plan.id
                or existing.parameters.get("plan_digest") != plan.plan_digest
                or plan.operation_id != existing.id
            ):
                raise KnowledgeIdempotencyConflictError()
            return JobAccepted(job_id=existing.id, state=existing.state, reused=True)
        if plan.operation_id is not None:
            raise KnowledgeIdempotencyConflictError()
        if not plan.target_manifest:
            raise KnowledgeOperationConfirmationRequiredError()
        preview = await self.owner.apreview(session, space_id, identity=identity, parameters=plan.parameters)
        scope = await self.scope.aload_scope(session, space_id, for_update=True)
        self.require_rebuild_scope_ready(scope)
        targets, source = self._versions(preview, scope)
        if (
            targets != plan.target_revisions
            or source != plan.source_revisions
            or [row.target.model_dump(mode="json") for row in scope] != plan.target_manifest
        ):
            raise KnowledgeOperationPlanChangedError()
        participants = tuple(row for row in scope if row.status == 2)
        if not participants:
            raise KnowledgeOperationConfirmationRequiredError()
        actual = await self.owner.aprepare(
            session,
            space_id,
            identity=identity,
            parameters=plan.parameters,
            operation_id=plan.id,
        )
        settings = await self.settings.aget(session, space_id)
        result = await self.jobs.acreate(
            session,
            space_id=space_id,
            kind=plan.operation,
            idempotency_key=request.idempotency_key,
            actor_user_id=actor.actor_user_id,
            actor_reference=actor.reference,
            parameters={
                "operation_id": plan.id,
                "confirmation_id": plan.id,
                "plan_digest": plan.plan_digest,
                "request_parameters": plan.parameters,
            },
            configuration=actual.configuration,
            space_config_version=settings.config_version,
            items=[
                NewProcessingItem(
                    target=row.target,
                    expected_space_id=space_id,
                    expected_parent_id=row.parent_id,
                    processing_snapshot={"mode": "existing_chunks", "original_status": 2},
                )
                for row in participants
            ],
        )
        await self.plans.aconsume(session, plan.id, operation_id=result.job.id, expected_digest=plan.plan_digest)
        return self._accepted(result)

    async def _job(self, session, space_id, job_id, identity):
        await self._authorize(identity, space_id)
        job = await self.jobs.aget(session, job_id)
        if job.space_id != space_id:
            raise KnowledgeProcessingJobNotFoundError()
        return job

    @staticmethod
    async def _visible(identity, job):
        ids = tuple(sorted({row["file_id"] for row in job.scope_manifest}))
        grants = await batch_check_business_actions(
            identity, resource_type="knowledge_file", resource_ids=ids, actions=("visible",)
        )
        return frozenset(value for value in ids if "visible" in grants.get(str(value), ()))

    @staticmethod
    def _read(job, visible, *, retryable):
        return ProcessingJobRead(
            id=job.id,
            space_id=job.space_id,
            kind=job.kind,
            state=job.state,
            revision=job.revision,
            accepted_at=job.accepted_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            total_count=job.total_count,
            succeeded_count=job.succeeded_count,
            failed_count=job.failed_count,
            pending_count=job.pending_count,
            hidden_item_count=sum(row["file_id"] not in visible for row in job.scope_manifest),
            retryable=retryable,
            obsolete_reason=job.obsolete_reason,
            error_code=job.error_code,
        )

    async def aget(self, session, space_id, job_id, *, identity):
        job = await self._job(session, space_id, job_id, identity)
        eligibility = await self.jobs.aretry_eligibility(session, job.id)
        return self._read(job, await self._visible(identity, job), retryable=eligibility.retryable)

    async def alist(self, session, space_id, *, identity, page=1, page_size=20, kind=None, state=None):
        await self._authorize(identity, space_id)
        result = await self.jobs.alist_jobs(session, space_id, page=page, page_size=page_size, kind=kind, state=state)
        return PageData[ProcessingJobRead](
            data=[
                self._read(
                    job,
                    await self._visible(identity, job),
                    retryable=(await self.jobs.aretry_eligibility(session, job.id)).retryable,
                )
                for job in result.rows
            ],
            total=result.total,
        )

    async def alist_items(self, session, space_id, job_id, *, identity, page=1, page_size=20, state=None):
        job = await self._job(session, space_id, job_id, identity)
        visible = await self._visible(identity, job)
        result = await self.jobs.alist_items(
            session, job_id, page=page, page_size=page_size, state=state, visible_file_ids=tuple(visible)
        )
        return PageData[ProcessingItemRead](
            data=[
                ProcessingItemRead(
                    id=row.id,
                    file_id=row.file_id,
                    document_id=row.document_id,
                    version_id=row.version_id,
                    step=row.step,
                    state=row.state,
                    attempt=row.attempt,
                    error_code=row.error_code,
                    retryable=job.state in {"partial_failed", "failed"} and row.state == "failed",
                )
                for row in result.rows
            ],
            total=result.total,
        )

    async def aretry(self, session, space_id, job_id, request, *, identity, entry_kind):
        request = ProcessingRetryRequest.model_validate(request.model_dump(mode="json"))
        job = await self._job(session, space_id, job_id, identity)
        self._kind(job.kind)
        actor = await capture_processing_actor(
            identity, space_id=space_id, required_action="edit", entry_kind=entry_kind
        )
        result = await self.owner.aretry_failed(
            session,
            job_id,
            idempotency_key=request.idempotency_key,
            expected_job_revision=request.expected_job_revision,
            actor_user_id=actor.actor_user_id,
            actor_reference=actor.reference,
            identity=identity,
        )
        if result.job.state == "obsolete":
            return ProcessingRetryOutcome(error=KnowledgeProcessingObsoleteError())
        return ProcessingRetryOutcome(data=self._accepted(result))
