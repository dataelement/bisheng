"""Native move composition and bounded, permission-filtered read streams."""

from contextlib import asynccontextmanager

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanChangedError,
    KnowledgeProcessingJobNotFoundError,
    KnowledgeProcessingObsoleteError,
)
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.common.schemas.api import PageData
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application import move_processing_admission as admission
from bisheng.knowledge.application.move_processing_owner import KnowledgeMoveProcessingOwner
from bisheng.knowledge.application.processing_identity import capture_processing_actor
from bisheng.knowledge.domain.repositories.move_query_repository import MoveQueryRepository
from bisheng.knowledge.domain.schemas.move_processing import MoveRoot
from bisheng.knowledge.domain.schemas.processing_job import ProcessingItemRead, ProcessingJobRead
from bisheng.permission.application.business_authorization import batch_check_business_actions
from bisheng.permission.application.data_scope import DATA_SCOPE_PERSONAL
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.permission.application.knowledge_move_projection import KnowledgeMoveProjectionApplication
from bisheng.resource_reference.application.access import get_reference_binding_runtime


async def get_move_owner():
    return KnowledgeMoveProcessingOwner(
        session_factory=get_async_db_session,
        projection=KnowledgeMoveProjectionApplication(session_factory=get_async_db_session),
        reference_runtime=await get_reference_binding_runtime(),
    )


class MoveProcessingAccess:
    def __init__(self, owner):
        if not isinstance(owner, KnowledgeMoveProcessingOwner):
            raise TypeError("actual move owner required")
        self.owner, self.rows = owner, MoveQueryRepository()

    @staticmethod
    def _page(page, page_size):
        if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 200:
            raise ValueError("bounded move page required")
        return (page - 1) * page_size

    async def _stable(self, session, job, reference):
        current, actual = await self.owner._job(session, job.id)
        if (current.revision, current.request_hash, current.parameters, actual) != (
            job.revision,
            job.request_hash,
            job.parameters,
            reference,
        ):
            raise KnowledgeOperationPlanChangedError()

    @asynccontextmanager
    async def _authorized(self, space_id, job_id, identity):
        async with self.owner._session() as session:
            header = await self.owner.jobs.aget_execution(session, job_id)
            if header.kind != "move_index" or space_id not in (
                header.space_id,
                header.parameters.get("source_space_id"),
            ):
                raise KnowledgeProcessingJobNotFoundError()
            job, reference = await self.owner._job(session, job_id)
            actor = admission.subject(reference)
            if actor.subject_id not in await self.owner.move_jobs.aoperator_membership(
                session, job_id=job.id, operator_ids=(actor.subject_id,)
            ):
                raise KnowledgeProcessingJobNotFoundError()
        async with admission.identity(reference, current=identity, entry_kind="web") as (actual, _):
            roots = ()
            if get_current_permission_actor().data_scope == DATA_SCOPE_PERSONAL:
                # Personal narrowing needs the original frozen selected roots.
                # Validate this one immutable Plan; never restore its full Scope
                # or repeat it for each Item/page. All-visible reads need no Plan JSON.
                async with self.owner._session() as session:
                    await self._stable(session, job, reference)
                    plan = await self.owner.move_jobs.aread_move_confirmation(
                        session,
                        source_space_id=job.parameters["source_space_id"],
                        confirmation_id=job.parameters["confirmation_id"],
                        plan_digest=job.parameters["plan_digest"],
                    )
                    roots = tuple(MoveRoot(row["type"], row["id"]) for row in plan.parameters["roots"])
            await admission.authorize(
                actual,
                roots=roots,
                destination_space_id=job.space_id,
                destination_folder_id=job.parameters["destination_folder_id"],
            )
            async with self.owner._session() as session:
                await self._stable(session, job, reference)
            yield job, reference, actual

    async def _visible_rows(self, job, reference, identity, *, state=None):
        after = None
        tenant, actor = admission.tenant(), get_current_permission_actor()
        while True:
            async with self.owner._session() as session:
                await self._stable(session, job, reference)
                rows = await self.rows.alist_items(session, job_id=job.id, after=after, state=state)
            if not rows:
                break
            ids = tuple(dict.fromkeys(row["file_id"] for row in rows))
            actions = await batch_check_business_actions(
                identity, resource_type="knowledge_file", resource_ids=ids, actions=("visible",)
            )
            if admission.tenant() != tenant or get_current_permission_actor() is not actor:
                raise PermissionDeniedError(reason="move_query_context_changed")
            yield tuple(row for row in rows if "visible" in actions.get(str(row["file_id"]), ()))
            if len(rows) < 200:
                break
            last = rows[-1]
            after = (last["file_id"], last["version_id"], last["id"])
        async with self.owner._session() as session:
            await self._stable(session, job, reference)

    async def aget(self, space_id, job_id, *, identity):
        async with self._authorized(space_id, job_id, identity) as (job, reference, actual):
            return await self._read(job, reference, actual)

    async def _read(self, job, reference, actual):
        visible = 0
        async for rows in self._visible_rows(job, reference, actual):
            visible += len(rows)
        async with self.owner._session() as session:
            eligibility = await self.owner.jobs.aretry_eligibility(session, job.id)
        # Keep the original public DTO/aggregate algorithm, with a scalar
        # hidden count instead of loading/re-expiring the public manifest.
        result = ProcessingJobRead(
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
            hidden_item_count=job.total_count - visible,
            retryable=eligibility.retryable,
            obsolete_reason=job.obsolete_reason,
            error_code=job.error_code,
        )
        return result

    async def alist(self, space_id, *, identity, page=1, page_size=20, state=None):
        offset = self._page(page, page_size)
        origin = await capture_processing_actor(identity, space_id=space_id, required_action="move", entry_kind="web")
        subject = admission.subject(origin.reference)
        after, selected, total = None, [], 0
        while True:
            async with self.owner._session() as session:
                candidates = await self.owner.move_jobs.alist_query_candidates(
                    session,
                    space_id=space_id,
                    subject_type=subject.subject_type,
                    subject_id=subject.subject_id,
                    ordered=True,
                    after=after,
                    state=state,
                )
            for job_id, _timestamp in candidates:
                try:
                    async with self._authorized(space_id, job_id, identity) as (job, reference, actual):
                        if offset <= total < offset + page_size:
                            selected.append(await self._read(job, reference, actual))
                        total += 1
                except (PermissionDeniedError, KnowledgeProcessingJobNotFoundError):
                    continue
            if len(candidates) < 200:
                break
            ident, timestamp = candidates[-1]
            after = (timestamp, ident)
        return PageData[ProcessingJobRead](data=selected, total=total)

    async def alist_items(self, space_id, job_id, *, identity, page=1, page_size=20, state=None):
        offset, total, selected = self._page(page, page_size), 0, []
        async with self._authorized(space_id, job_id, identity) as (job, reference, actual):
            # The original scalar eligibility read proves the complete Item count.
            async with self.owner._session() as session:
                await self.owner.jobs.aretry_eligibility(session, job.id)
            async for rows in self._visible_rows(job, reference, actual, state=state):
                for row in rows:
                    if offset <= total < offset + page_size:
                        selected.append(
                            ProcessingItemRead(
                                **{
                                    key: row[key]
                                    for key in (
                                        "id",
                                        "file_id",
                                        "document_id",
                                        "version_id",
                                        "step",
                                        "state",
                                        "attempt",
                                        "error_code",
                                    )
                                },
                                retryable=job.state in {"partial_failed", "failed"} and row["state"] == "failed",
                            )
                        )
                    total += 1
        return PageData[ProcessingItemRead](data=selected, total=total)

    async def aretry(self, space_id, job_id, request, *, identity):
        async with self.owner._session() as session:
            job = await self.owner.jobs.aget_execution(session, job_id)
            if job.kind != "move_index" or space_id not in (job.space_id, job.parameters.get("source_space_id")):
                raise KnowledgeProcessingJobNotFoundError()
        result = await self.owner.aretry_failed(job_id, request, identity=identity, entry_kind="web")
        if result.state == "obsolete":
            raise KnowledgeProcessingObsoleteError()
        return result
