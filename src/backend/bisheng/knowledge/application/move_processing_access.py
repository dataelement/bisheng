"""Process composition and HTTP access for the actual move application."""

from bisheng.common.errcode.knowledge import KnowledgeProcessingJobNotFoundError, KnowledgeProcessingObsoleteError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.common.schemas.api import PageData
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application import move_processing_admission as admission
from bisheng.knowledge.application.move_processing_owner import KnowledgeMoveProcessingOwner
from bisheng.knowledge.application.processing_identity import capture_processing_actor
from bisheng.knowledge.domain.schemas.processing_job import ProcessingItemRead, ProcessingJobRead
from bisheng.knowledge.domain.services.processing_job_service import ProcessingJobService
from bisheng.permission.application.business_authorization import batch_check_business_actions
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.permission.application.knowledge_move_projection import KnowledgeMoveProjectionApplication
from bisheng.resource_reference.application.access import get_reference_binding_runtime


async def get_move_owner():
    # P1 resolves the process's registered F048 components; R2 has no fallback.
    return KnowledgeMoveProcessingOwner(
        session_factory=get_async_db_session,
        projection=KnowledgeMoveProjectionApplication(session_factory=get_async_db_session),
        reference_runtime=await get_reference_binding_runtime(),
    )


class MoveProcessingAccess:
    """Move reads use current typed continuation and the original detail trimming."""

    def __init__(self, owner):
        if not isinstance(owner, KnowledgeMoveProcessingOwner):
            raise TypeError("actual move owner required")
        self.owner = owner

    async def _readable(self, space_id, job_id, identity):
        async with self.owner._session() as session:
            job = await self.owner.jobs.aget(session, job_id)
            if job.kind != "move_index" or space_id not in (job.space_id, job.parameters.get("source_space_id")):
                raise KnowledgeProcessingJobNotFoundError()
            job, reference = await self.owner._job(session, job_id)
            scope = await self.owner._scope_for(session, job)
            actor = admission.subject(reference)
            members = await self.owner.move_jobs.aoperator_membership(
                session, job_id=job.id, operator_ids=(actor.subject_id,)
            )
            if actor.subject_id not in members:
                raise KnowledgeProcessingJobNotFoundError()
            eligibility = await self.owner.jobs.aretry_eligibility(session, job.id)
            # Read the public compact manifest only after scalar eligibility,
            # whose execution getter deliberately defers it.
            job = await self.owner.jobs.aget(session, job.id)
            session.expunge(job)
        async with admission.identity(reference, current=identity, entry_kind="web") as (actual, _):
            await admission.authorize(
                actual,
                roots=scope.roots,
                destination_space_id=scope.destination_space_id,
                destination_folder_id=scope.destination_folder_id,
            )
            ids = sorted({row["file_id"] for row in job.scope_manifest})
            visible = set()
            tenant, current_actor = admission.tenant(), get_current_permission_actor()
            for offset in range(0, len(ids), 200):
                grants = await batch_check_business_actions(
                    actual,
                    resource_type="knowledge_file",
                    resource_ids=tuple(ids[offset : offset + 200]),
                    actions=("visible",),
                )
                if admission.tenant() != tenant or get_current_permission_actor() is not current_actor:
                    raise PermissionDeniedError(reason="move_query_context_changed")
                visible.update(value for value in ids[offset : offset + 200] if "visible" in grants.get(str(value), ()))
        return job, frozenset(visible), eligibility

    async def aget(self, space_id, job_id, *, identity):
        job, visible, eligibility = await self._readable(space_id, job_id, identity)
        return ProcessingJobService._read(job, visible, retryable=eligibility.retryable)

    async def alist(self, space_id, *, identity, page=1, page_size=20, state=None):
        if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 200:
            raise ValueError("bounded move page required")
        origin = await capture_processing_actor(identity, space_id=space_id, required_action="move", entry_kind="web")
        subject = admission.subject(origin.reference)
        after, rows = None, []
        while True:
            async with self.owner._session() as session:
                candidates = await self.owner.move_jobs.alist_query_candidates(
                    session,
                    space_id=space_id,
                    subject_type=subject.subject_type,
                    subject_id=subject.subject_id,
                    after_id=after,
                    state=state,
                )
            for job_id in candidates:
                try:
                    rows.append(await self.aget(space_id, job_id, identity=identity))
                except (PermissionDeniedError, KnowledgeProcessingJobNotFoundError):
                    # A coarse candidate is not authority and must not contribute to total.
                    continue
            if len(candidates) < 200:
                break
            after = candidates[-1]
        rows.sort(key=lambda row: (row.accepted_at, row.id), reverse=True)
        offset = (page - 1) * page_size
        return PageData[ProcessingJobRead](data=rows[offset : offset + page_size], total=len(rows))

    async def alist_items(self, space_id, job_id, *, identity, page=1, page_size=20, state=None):
        if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 200:
            raise ValueError("bounded move page required")
        job, visible, _ = await self._readable(space_id, job_id, identity)
        ids, rows, total = sorted(visible), [], 0
        # Reuse the native pagination algorithm with bounded IN arguments. Each
        # disjoint chunk contributes its count and at most this page's prefix.
        for offset in range(0, len(ids), 200):
            for number in range(1, page + 1):
                async with self.owner._session() as session:
                    result = await self.owner.jobs.alist_items(
                        session,
                        job_id,
                        page=number,
                        page_size=page_size,
                        visible_file_ids=tuple(ids[offset : offset + 200]),
                        state=state,
                    )
                    for row in result.rows:
                        session.expunge(row)
                if number == 1:
                    total += result.total
                rows.extend(result.rows)
                if len(result.rows) < page_size:
                    break
        rows.sort(key=lambda row: (row.file_id, row.version_id, row.id))
        offset = (page - 1) * page_size
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
                for row in rows[offset : offset + page_size]
            ],
            total=total,
        )

    async def aretry(self, space_id, job_id, request, *, identity):
        # A different typed subject can enter explicit retry; the actual Owner
        # then checks current selected-resource move + destination upload.
        async with self.owner._session() as session:
            job = await self.owner.jobs.aget_execution(session, job_id)
            if job.kind != "move_index":
                raise KnowledgeProcessingJobNotFoundError()
            job, _ = await self.owner._job(session, job_id)
            if space_id not in (job.space_id, job.parameters["source_space_id"]):
                raise KnowledgeProcessingJobNotFoundError()
        accepted = await self.owner.aretry_failed(job_id, request, identity=identity, entry_kind="web")
        if accepted.state == "obsolete":
            raise KnowledgeProcessingObsoleteError()
        return accepted
