"""Copy-specific bounded getters over the original job/lease/count kernel."""

from sqlalchemy import select
from sqlalchemy.orm import defer

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError, KnowledgeProcessingJobNotFoundError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.repositories.processing_job_repository import ProcessingJobRepository
from bisheng.knowledge.domain.repositories.space_copy_repository import SpaceCopyRepository


class SpaceCopyJobRepository(ProcessingJobRepository):
    async def _job(self, session, job_id, *, lock, include_manifest=True):
        query = select(Job).where(Job.id == job_id, Job.kind == "space_copy")
        if not include_manifest:
            query = query.options(defer(Job.scope_manifest, raiseload=True), defer(Job.parameters, raiseload=True))
            query = query.execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        with session.no_autoflush, strict_tenant_filter():
            row = (await session.execute(query)).scalar_one_or_none()
        if row is None or row.tenant_id != self._tenant_id():
            raise KnowledgeProcessingJobNotFoundError()
        return row

    async def _execution_job(self, session, job_id, *, _move=False):
        header = await self.aread_transport(session, job_id)
        if header.kind != "space_copy" or _move:
            raise KnowledgeProcessingJobNotFoundError()
        root = await SpaceCopyRepository().aroot(session, header.space_id, lock=True)
        if root.state != 3:
            raise KnowledgeProcessingConflictError(reason="copy_permission_not_ready")
        return await self._job(session, job_id, lock=True, include_manifest=False), None
