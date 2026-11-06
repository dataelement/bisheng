"""Knowledge's actual model configuration for durable processing operations.

All reads and R2 writes borrow the caller's transaction. A model ID in a job
is never an execution binding: the current business source admits every read.
"""

import json
from dataclasses import dataclass

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.background_execution import get_current_background_task
from bisheng.knowledge.application.model_reference import (
    KnowledgeModelReferenceApplication,
    PreparedKnowledgeModelChange,
)
from bisheng.knowledge.application.model_reference_read import AdmittedKnowledgeModel, get_knowledge_model_read_runtime
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.repositories.processing_job_repository import (
    ProcessingConfiguration,
    ProcessingJobRepository,
)
from bisheng.knowledge.domain.schemas.processing_job import EmbeddingRebuildParameters
from bisheng.knowledge.domain.services.processing_cutover_receipts import _ProcessingCutoverAuthority
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_endpoints.domain.utils import get_open_api_operator_async


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


class _CutoverNotReady(Exception):
    """The locking read rejected this worker before any business mutation."""


class KnowledgeProcessingOwner:
    def __init__(self, *, jobs=None):
        self.jobs = jobs if jobs is not None else ProcessingJobRepository()
        self._cutovers = _ProcessingCutoverAuthority(self)

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
        return await self.jobs.afinalize(session, lease, configuration=current.configuration)

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
