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

    async def aread_item_snapshot(self, session, *, job_id, item_id):
        from copy import deepcopy

        from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item

        with session.no_autoflush, strict_tenant_filter():
            row = (
                await session.execute(
                    select(Item.tenant_id, Item.processing_snapshot).where(Item.id == item_id, Item.job_id == job_id)
                )
            ).one_or_none()
        if row is None or row.tenant_id != self._tenant_id():
            raise KnowledgeProcessingJobNotFoundError()
        return deepcopy(row.processing_snapshot)

    async def aread_transport(self, session, job_id):
        from types import SimpleNamespace

        with session.no_autoflush, strict_tenant_filter():
            row = (
                await session.execute(
                    select(Job.id, Job.tenant_id, Job.space_id, Job.kind, Job.revision).where(
                        Job.id == job_id, Job.kind == "space_copy"
                    )
                )
            ).one_or_none()
        if row is None or row.tenant_id != self._tenant_id():
            raise KnowledgeProcessingJobNotFoundError()
        return SimpleNamespace(**row._mapping)

    async def _execution_job(self, session, job_id, *, _move=False):
        header = await self.aread_transport(session, job_id)
        if header.kind != "space_copy" or _move:
            raise KnowledgeProcessingJobNotFoundError()
        root = await SpaceCopyRepository().aroot(session, header.space_id, lock=True)
        if root.state != 2:
            raise KnowledgeProcessingConflictError(reason="copy_permission_not_ready")
        return await self._job(session, job_id, lock=True, include_manifest=False), None

    async def alist_ids(self, session, space_id, *, page, page_size, state=None):
        from sqlalchemy import func

        from bisheng.knowledge.domain.schemas.processing_job import JobState

        offset = self._page(page, page_size)
        filters = [Job.tenant_id == self._tenant_id(), Job.space_id == space_id, Job.kind == "space_copy"]
        if state is not None:
            filters.append(Job.state == JobState(state).value)
        with session.no_autoflush, strict_tenant_filter():
            total = (await session.execute(select(func.count()).select_from(Job).where(*filters))).scalar_one()
            ids = (
                (
                    await session.execute(
                        select(Job.id)
                        .where(*filters)
                        .order_by(Job.accepted_at.desc(), Job.id.desc())
                        .offset(offset)
                        .limit(page_size)
                    )
                )
                .scalars()
                .all()
            )
        return ids, total
