"""Target-space copy queries reuse the original scalar visibility projections."""

from contextlib import asynccontextmanager

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeProcessingJobNotFoundError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.common.schemas.api import PageData
from bisheng.knowledge.application import move_processing_admission as admission
from bisheng.knowledge.application.move_processing_access import MoveProcessingAccess
from bisheng.knowledge.application.space_copy_owner import SpaceCopyOwner
from bisheng.knowledge.domain.repositories.move_query_repository import MoveQueryRepository
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.permission.application.identity import resolve_permission_actor


class SpaceCopyAccess(MoveProcessingAccess):
    def __init__(self, owner=None):
        self.owner, self.rows = owner or SpaceCopyOwner(), MoveQueryRepository(kind="space_copy")

    async def _target(self, space_id, identity):
        admission.tenant()
        async with self.owner._session() as session:
            root = await self.owner.rows.aroot(session, space_id)
        actor = await resolve_permission_actor(identity)
        if actor is None or (actor.subject_type, actor.subject_id) != ("user", root.user_id):
            raise PermissionDeniedError(reason="space_copy_actual_creator_required")
        await require_business_action(identity, resource_type="knowledge_space", resource_id=space_id, action="edit")
        return root

    @asynccontextmanager
    async def _authorized(self, space_id, job_id, identity):
        job, reference = await self.owner.aread(job_id)
        if job.space_id != space_id:
            raise KnowledgeProcessingJobNotFoundError()
        async with admission.identity(reference, current=identity, entry_kind="web", required_action="upload_file") as (
            actual,
            _,
        ):
            await self._target(space_id, actual)
            yield job, reference, actual

    async def _stable(self, session, job, reference):
        current = await self.owner.jobs.aget_execution(session, job.id)
        latest = await self.owner.jobs.alatest_retry_actor(session, job.id)
        if (current.revision, current.request_hash, latest) != (job.revision, job.request_hash, reference):
            raise KnowledgeOperationPlanChangedError()

    async def alist(self, space_id, *, identity, page=1, page_size=20, state=None):
        await self._target(space_id, identity)
        async with self.owner._session() as session:
            ids, total = await self.owner.jobs.alist_ids(session, space_id, page=page, page_size=page_size, state=state)
        return PageData(data=[await self.aget(space_id, ident, identity=identity) for ident in ids], total=total)

    async def aretry(self, space_id, job_id, request, *, identity):
        async with self._authorized(space_id, job_id, identity):
            return await self.owner.aretry(job_id, request, identity=identity)
