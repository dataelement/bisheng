"""Knowledge's actual model configuration for durable processing operations.

All reads and R2 writes borrow the caller's transaction. A model ID in a job
is never an execution binding: the current business source admits every read.
"""

import json
from dataclasses import dataclass

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.core.context.background_execution import get_current_background_task
from bisheng.knowledge.application.file_processing_adapter import (
    legacy_rule_from_snapshot,
    resolve_file_processing_snapshot,
    system_processing_defaults,
)
from bisheng.knowledge.application.model_reference import (
    KnowledgeModelReferenceApplication,
    PreparedKnowledgeModelChange,
)
from bisheng.knowledge.application.model_reference_read import AdmittedKnowledgeModel, get_knowledge_model_read_runtime
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.repositories.processing_job_repository import (
    NewProcessingItem,
    ProcessingConfiguration,
    ProcessingJobRepository,
)
from bisheng.knowledge.domain.repositories.processing_owner_repository import ProcessingOwnerRepository
from bisheng.knowledge.domain.repositories.processing_settings_repository import ProcessingSettingsRepository
from bisheng.knowledge.domain.schemas.processing_job import EmbeddingRebuildParameters
from bisheng.knowledge.domain.schemas.processing_settings import ProcessingDefaults
from bisheng.knowledge.domain.services.processing_cutover_receipts import _ProcessingCutoverAuthority
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_endpoints.domain.utils import get_open_api_operator_async
from bisheng.permission.application.business_authorization import require_business_action


@dataclass(frozen=True, slots=True)
class ProcessingBusinessState:
    admitted: AdmittedKnowledgeModel

    @property
    def model_id(self):
        return self.admitted.model_id

    @property
    def operation_id(self):
        return self.admitted.operation_id

    @property
    def configuration(self):
        return ProcessingConfiguration(self.admitted.model_config_revision, self.admitted.index_generation)


@dataclass(frozen=True, slots=True)
class PreparedFileProcessingPlan:
    configuration: ProcessingConfiguration
    source_revisions: dict
    items: tuple[NewProcessingItem, ...]


class _CutoverNotReady(Exception):
    """The locking read rejected this worker before any business mutation."""


class KnowledgeProcessingOwner:
    def __init__(self, *, jobs=None):
        self.jobs = jobs if jobs is not None else ProcessingJobRepository()
        self.scope = ProcessingOwnerRepository()
        self._cutovers = _ProcessingCutoverAuthority(self)

    async def apreview_file_processing(self, session, space_id, *, identity, kind, targets, overrides):
        if kind not in {"file_reprocess", "file_resplit"}:
            raise KnowledgeProcessingConflictError(reason="processing_kind_unavailable")
        await self._operator(identity)
        await require_business_action(identity, resource_type="knowledge_space", resource_id=space_id, action="edit")
        scope = await self.scope.aload_scope(session, space_id, targets=targets, for_update=True)
        await self.scope.aassert_file_processing_available(session, space_id, scope)
        current = await self.aread_current(session, space_id, identity=identity)
        settings = await ProcessingSettingsRepository().aget(session, space_id)
        defaults = (
            ProcessingDefaults.model_validate(settings.saved_defaults) if settings.saved_defaults is not None else None
        )
        items = []
        for row in scope:
            effective = resolve_file_processing_snapshot(
                file_name=row.file_name,
                file_source=row.file_source,
                system_defaults=system_processing_defaults(space_id),
                space_defaults=defaults,
                space_config_version=settings.config_version,
                batch_overrides=overrides,
                legacy_split_rule=row.split_rule,
            )
            items.append(
                NewProcessingItem(
                    target=row.target,
                    expected_space_id=space_id,
                    expected_parent_id=row.parent_id,
                    processing_snapshot={
                        "schema_version": 1,
                        "mode": kind,
                        "original_status": row.status,
                        "effective_processing": effective.model_dump(mode="json"),
                        "source_revision": row.source_revision,
                    },
                )
            )
        revisions = {
            "model_config_revision": current.configuration.model_config_revision,
            "index_generation": current.configuration.index_generation,
            "processing_config_version": settings.config_version,
            "versions": {f"{row.target.file_id}:{row.target.version_id}": row.revision for row in scope},
        }
        return PreparedFileProcessingPlan(current.configuration, revisions, tuple(items))

    async def aprepare_file_processing(
        self,
        session,
        space_id,
        *,
        identity,
        kind,
        targets,
        overrides,
        expected_configuration,
        expected_source_revisions,
        operation_id,
    ):
        if not isinstance(operation_id, str) or not operation_id:
            raise KnowledgeOperationPlanConflictError(reason="processing_file_operation_required")
        plan = await self.apreview_file_processing(
            session, space_id, identity=identity, kind=kind, targets=targets, overrides=overrides
        )
        if plan.configuration != expected_configuration or plan.source_revisions != expected_source_revisions:
            raise KnowledgeOperationPlanConflictError(reason="processing_file_plan_changed")
        operator = await self._operator(identity)
        rules = {
            item.target.file_id: legacy_rule_from_snapshot(
                item.processing_snapshot["effective_processing"], space_id=space_id
            ).model_dump_json()
            for item in plan.items
        }
        await self.scope.aqueue_file_processing(
            session, space_id, plan.items, rules=rules, actor_user_id=operator.user_id
        )
        return plan.items

    @staticmethod
    async def _operator(identity):
        if isinstance(identity, UserPayload):
            return identity
        if (
            isinstance(identity, OpenApiPrincipal)
            and get_current_open_api_principal() is identity
            and identity.has_scope("knowledge:write")
        ):
            # Existing v2 compatibility projection preserves the ambient SA/D
            # PermissionActor. This payload supplies persistence/audit fields.
            return await get_open_api_operator_async()
        raise ResourceReferenceInvalidError(reason="processing_original_identity_required")

    async def aread_current(self, session, space_id, *, identity=None, job=None) -> ProcessingBusinessState:
        if isinstance(identity, OpenApiPrincipal):
            if get_current_open_api_principal() is not identity:
                raise ResourceReferenceInvalidError(reason="processing_original_identity_required")
            login_user = None
        else:
            login_user = identity
        runtime = await get_knowledge_model_read_runtime()
        admitted = await runtime.arequire(space_id, login_user=login_user, session=session)
        row = json.loads(admitted.read.snapshot.payload_json)["knowledge"]
        if row["type"] != KnowledgeTypeEnum.SPACE.value:
            raise ResourceReferenceInvalidError(reason="processing_space_required")
        if job is not None:
            if (
                job.space_id != space_id
                or admitted.model_config_revision != job.expected_model_config_revision
                or admitted.index_generation != job.expected_index_generation
            ):
                raise KnowledgeOperationPlanConflictError(reason="knowledge_model_operation_obsolete")
            if admitted.operation_id is not None:
                if admitted.operation_id != job.parameters.get("operation_id"):
                    raise KnowledgeOperationPlanConflictError(reason="knowledge_model_operation_obsolete")
                admitted = await runtime.arequire(
                    space_id,
                    login_user=login_user,
                    session=session,
                    slot_key="model_transition.pending_model_id",
                    expected_operation_id=admitted.operation_id,
                    expected_model_config_revision=job.expected_model_config_revision,
                    expected_index_generation=job.expected_index_generation,
                )
        return ProcessingBusinessState(admitted)

    async def _aperform_model_cutover(self, session, job, lease):
        # Existing R2 takes model/parent locks before the Knowledge root. Only
        # then lock the task, preserving the creation-side resource->job order.
        plan = await KnowledgeModelReferenceApplication.aprepare_finalization(
            session,
            job.space_id,
            operation_id=job.parameters["operation_id"],
            expected_model_config_revision=job.expected_model_config_revision,
            expected_index_generation=job.expected_index_generation,
        )
        locked = await self.jobs._job(session, job.id, lock=True)
        if locked is not job or not self.jobs._active_job_lease(locked, lease):
            raise _CutoverNotReady()
        await self.jobs._refresh_counts(session, locked)
        if locked.pending_count:
            raise _CutoverNotReady()
        if (locked.expected_model_config_revision, locked.expected_index_generation) != (
            plan.expected_revision,
            plan.expected_generation,
        ) or locked.parameters.get("operation_id") != plan.operation_id:
            raise KnowledgeOperationPlanConflictError(reason="knowledge_model_operation_obsolete")
        return await KnowledgeModelReferenceApplication.aapply_finalization(session, plan)

    async def afinalize_and_ack(self, session, job, lease):
        actual = await self.jobs.aget(session, lease.job_id)
        if (
            actual is not job
            or type(job.accepted_model_config_revision) is not int
            or job.accepted_model_config_revision < 0
        ):
            raise ResourceReferenceInvalidError(reason="processing_cutover_original_evidence_required")
        background = get_current_background_task()
        if background is None or background.tenant_id != job.tenant_id:
            raise ResourceReferenceInvalidError(reason="processing_cutover_background_required")
        if not self.jobs._active_job_lease(job, lease):
            return None
        current = await self.aread_current(session, job.space_id, job=job)
        if current.operation_id is not None:
            try:
                receipt = await self._cutovers.afinalize(session, job, lease)
            except _CutoverNotReady:
                return None
            acknowledged = await self.jobs.aacknowledge_cutover(session, lease, receipt=receipt)
            if acknowledged is None:
                raise ResourceReferenceInvalidError(reason="processing_cutover_lease_changed")
            current = await self.aread_current(session, job.space_id, job=job)
        return await self.scope.afinalize_attempt(session, lease, jobs=self.jobs)

    async def abegin_retry_fence(self, session, job, *, identity):
        await self._operator(identity)
        await require_business_action(
            identity, resource_type="knowledge_space", resource_id=job.space_id, action="edit"
        )
        await self.aread_current(session, job.space_id, identity=identity, job=job)
        await self.scope.abegin_retry_fence(session, job, jobs=self.jobs)

    async def aretry_failed(
        self, session, job_id, *, identity, idempotency_key, expected_job_revision, actor_user_id, actor_reference
    ):
        await self._operator(identity)
        job = await self.jobs.aget(session, job_id)
        await require_business_action(
            identity, resource_type="knowledge_space", resource_id=job.space_id, action="edit"
        )
        # Keep the established business-resource -> job locking order. The
        # SourceOwner revalidates the real current binding in this transaction.
        _, job = await self.scope._attempt(session, job_id, self.jobs)
        current = await self.aread_current(session, job.space_id, identity=identity)
        result = await self.jobs.aretry_failed(
            session,
            job_id,
            idempotency_key=idempotency_key,
            expected_job_revision=expected_job_revision,
            actor_user_id=actor_user_id,
            actor_reference=actor_reference,
            configuration=current.configuration,
        )
        if not result.reused and result.job.state == "accepted":
            if result.job.kind in {"file_reprocess", "file_resplit"}:
                await self.scope.aqueue_retry_file_processing(session, result.job, jobs=self.jobs)
            else:
                await self.abegin_retry_fence(session, result.job, identity=identity)
        return result

    async def afail_attempt(self, session, job_id, *, expected_job_revision, error_code, lease=None):
        return await self.scope.afail_attempt(
            session,
            job_id,
            jobs=self.jobs,
            expected_job_revision=expected_job_revision,
            error_code=error_code,
            lease=lease,
        )

    async def apreview(
        self,
        session,
        space_id,
        *,
        identity,
        parameters,
        operation_id: str | None = None,
        expected_configuration: ProcessingConfiguration | None = None,
    ) -> PreparedKnowledgeModelChange:
        operator = await self._operator(identity)
        request = EmbeddingRebuildParameters.model_validate(parameters)
        row = await KnowledgeModelReferenceApplication.repository.aget(session, space_id)
        if row is None or row.type != KnowledgeTypeEnum.SPACE.value:
            raise ResourceReferenceInvalidError(reason="processing_space_required")
        selected = request.embedding_model_id if request.embedding_model_id is not None else row.model
        expected = {}
        if expected_configuration is not None:
            expected = {
                "expected_model_config_revision": expected_configuration.model_config_revision,
                "expected_index_generation": expected_configuration.index_generation,
            }
        return await KnowledgeModelReferenceApplication.aprepare_rebuild(
            session, space_id, selected, login_user=operator, operation_id=operation_id, **expected
        )

    async def aprepare(
        self, session, space_id, *, identity, parameters, operation_id, expected_configuration=None
    ) -> ProcessingBusinessState:
        plan = await self.apreview(
            session,
            space_id,
            identity=identity,
            parameters=parameters,
            operation_id=operation_id,
            expected_configuration=expected_configuration,
        )
        await KnowledgeModelReferenceApplication.aapply_model_change(session, plan)
        # This checks the actual new pending slot, complete source and current
        # model eligibility, including repair of an invalid old binding.
        runtime = await get_knowledge_model_read_runtime()
        admitted = await runtime.arequire(
            space_id,
            login_user=identity if isinstance(identity, UserPayload) else None,
            session=session,
            slot_key="model_transition.pending_model_id",
            expected_operation_id=plan.operation_id,
            expected_model_config_revision=plan.row.model_config_revision,
            expected_index_generation=plan.row.index_generation,
        )
        return ProcessingBusinessState(admitted)
