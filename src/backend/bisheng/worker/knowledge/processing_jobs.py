"""Existing Celery/Beat transport for the durable knowledge processing ledger."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta

from loguru import logger

from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge import (
    KnowledgeFileFailedError,
    KnowledgeProcessingConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.core.context.background_execution import get_current_background_task
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.processing_identity import restore_processing_actor
from bisheng.knowledge.application.processing_owner import KnowledgeProcessingOwner
from bisheng.knowledge.domain.repositories.processing_owner_repository import ProcessingOwnerRepository
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget
from bisheng.knowledge.domain.services.processing_job_service import ProcessingJobService
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.information.reconcile import _active_tenant_ids
from bisheng.worker.knowledge import metadata_jobs
from bisheng.worker.knowledge.file_worker import prepare_processing_file, write_processing_file
from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_processing_file, reset_processing_target
from bisheng.worker.main import bisheng_celery

EXECUTE_TASK = "bisheng.worker.knowledge.processing_jobs.execute_processing_job"
SCAN_TASK = "bisheng.worker.knowledge.processing_jobs.dispatch_pending_processing_jobs"
PROCESSING_HANDLERS = {
    "embedding_rebuild": rebuild_processing_file,
    "file_reprocess": prepare_processing_file,
    "file_resplit": prepare_processing_file,
}
_FILE_KINDS = frozenset({"file_reprocess", "file_resplit"})


def _new_owner():
    return KnowledgeProcessingOwner()


def _task_proof():
    proof = get_current_background_task()
    if proof is None or proof.tenant_id != get_current_tenant_id() or proof.task_name != EXECUTE_TASK:
        raise ResourceReferenceInvalidError(reason="processing_actual_worker_required")
    return proof


def _summary(job):
    return {"job_id": job.id, "state": job.state}


@asynccontextmanager
async def _actor(reference, tenant_id, space_id):
    if reference.get("space_id") != space_id or reference.get("required_action") != "edit":
        raise ResourceReferenceInvalidError(reason="processing_actor_scope_changed")
    async with restore_processing_actor(reference, tenant_id=tenant_id) as identity:
        await require_business_action(identity, resource_type="knowledge_space", resource_id=space_id, action="edit")
        yield identity


async def _failed(owner, job_id, revision, lease, error_code):
    async with get_async_db_session() as session:
        changed = await owner.afail_attempt(
            session,
            job_id,
            expected_job_revision=revision,
            lease=lease,
            error_code=error_code,
        )
        current = changed if changed is not None else await owner.jobs.aget(session, job_id)
        result = _summary(current)
        await session.commit()
        return result


async def _finalize(owner, job_id, lease):
    # The item transaction has committed. Existing model/R2 finalization takes
    # its target locks before root/job locks in this fresh transaction.
    async with get_async_db_session() as session:
        job = await owner.jobs.aget(session, job_id)
        final = await owner.afinalize_and_ack(session, job, lease)
        result = _summary(final if final is not None else job)
        await session.commit()
        return result


async def _execute_file_item(
    owner, scope, *, reference, proof, space_id, job_id, item_lease, file_id, kind, snapshot, configuration
):
    arguments = {
        "space_id": space_id,
        "invoke_user_id": reference["actor_user_id"],
        "expected_model_config_revision": configuration.model_config_revision,
        "expected_index_generation": configuration.index_generation,
    }
    async with _actor(reference, proof.tenant_id, space_id):
        prepared = await asyncio.to_thread(
            PROCESSING_HANDLERS[kind], file_id, kind=kind, processing_snapshot=snapshot, **arguments
        )
    # Prepared docs live only in memory. This persisted checkpoint carries
    # progress/counts; lease takeover repeats the real parse from frozen rules.
    async with _actor(reference, proof.tenant_id, space_id) as identity:
        async with get_async_db_session() as session:
            guarded = await scope.aguard_processed_file(session, item_lease, jobs=owner.jobs)
            if guarded is None:
                result = _summary(await owner.jobs.aget(session, job_id))
                await session.commit()
                return False, result
            current = await owner.aread_current(session, space_id, identity=identity, job=guarded[0])
            checkpoint = {**guarded[1].checkpoint, "chunk_count": len(prepared.documents)}
            if not await owner.jobs.asave_checkpoint(
                session, item_lease, configuration=current.configuration, step="file_prepared", checkpoint=checkpoint
            ):
                result = _summary(await owner.jobs.aget(session, job_id))
                await session.commit()
                return False, result
            await session.commit()
        outcome = await asyncio.to_thread(write_processing_file, prepared, **arguments)
    async with _actor(reference, proof.tenant_id, space_id) as identity:
        async with get_async_db_session() as session:
            guarded = await scope.aguard_processed_file(session, item_lease, jobs=owner.jobs)
            if guarded is None:
                result = _summary(await owner.jobs.aget(session, job_id))
                await session.commit()
                return False, result
            await owner.aread_current(session, space_id, identity=identity, job=guarded[0])
            completed = await scope.acomplete_processed_file(session, item_lease, jobs=owner.jobs, outcome=outcome)
            result = _summary(await owner.jobs.aget(session, job_id))
            await session.commit()
            return completed, result


async def _execute_processing_job(job_id: str, expected_dispatch_revision: int):
    proof = _task_proof()
    owner = _new_owner()
    scope = ProcessingOwnerRepository()
    lease = None
    revision = expected_dispatch_revision
    async with get_async_db_session() as session:
        job = await owner.jobs.aget_execution(session, job_id)
        if job.revision != expected_dispatch_revision or job.state not in {"accepted", "running"}:
            return _summary(job)
        space_id, kind, operation_id = job.space_id, job.kind, job.parameters.get("operation_id")
        if kind != "move_index":
            reference = await owner.jobs.alatest_retry_actor(session, job_id)
    if kind == "move_index":
        from bisheng.worker.knowledge import move_jobs

        return await move_jobs.execute_move_job(
            job_id, expected_dispatch_revision, owner=await move_jobs.get_move_owner(), proof=proof
        )
    if kind == "metadata_schema_change":
        return await metadata_jobs.execute_metadata_job(job_id, expected_dispatch_revision, owner=owner, proof=proof)
    try:
        if kind not in PROCESSING_HANDLERS:
            raise KnowledgeProcessingConflictError(reason="processing_kind_unavailable")
        async with _actor(reference, proof.tenant_id, space_id) as identity:
            async with get_async_db_session() as session:
                current = await owner.aread_current(session, space_id, identity=identity)
                # Check the complete current version set; never silently omit
                # a concurrently parsing version from an accepted rebuild.
                if kind == "embedding_rebuild":
                    ProcessingJobService.require_rebuild_scope_ready(
                        await scope.aload_scope(session, space_id, for_update=True)
                    )
                else:
                    await scope._attempt(session, job_id, owner.jobs)
                lease = await owner.jobs.aclaim(
                    session,
                    job_id,
                    configuration=current.configuration,
                    expected_job_revision=expected_dispatch_revision,
                )
                job = await owner.jobs.aget(session, job_id)
                result = _summary(job)
                revision = job.revision
                await session.commit()
                if lease is None:
                    return result
        while True:
            async with _actor(reference, proof.tenant_id, space_id) as identity:
                async with get_async_db_session() as session:
                    _, job = await scope._attempt(session, job_id, owner.jobs)
                    current = await owner.aread_current(session, space_id, identity=identity)
                    renewed = await owner.jobs.arenew(session, lease, configuration=current.configuration)
                    if renewed is None:
                        result = _summary(job)
                        await session.commit()
                        return result
                    lease = renewed
                    reset = (
                        await owner.jobs.areset_target_state(session, lease) if kind == "embedding_rebuild" else None
                    )
                    if kind == "embedding_rebuild" and reset is None:
                        result = _summary(job)
                        await session.commit()
                        return result
                    claimed = await owner.jobs.aclaim_next_item(session, lease, configuration=current.configuration)
                    if claimed is None:
                        await session.commit()
                        return await _finalize(owner, job_id, lease)
                    if kind in _FILE_KINDS:
                        if not await scope.astart_processed_file(session, claimed.lease, jobs=owner.jobs):
                            result = _summary(await owner.jobs.aget(session, job_id))
                            await session.commit()
                            return result
                        file_id, snapshot = claimed.item.file_id, deepcopy(claimed.item.processing_snapshot)
                        await session.commit()
                        completed, result = await _execute_file_item(
                            owner,
                            scope,
                            reference=reference,
                            proof=proof,
                            space_id=space_id,
                            job_id=job_id,
                            item_lease=claimed.lease,
                            file_id=file_id,
                            kind=kind,
                            snapshot=snapshot,
                            configuration=current.configuration,
                        )
                        if not completed:
                            return result
                        continue
                    if claimed.item.processing_snapshot.get("original_status") != 2:
                        raise ResourceReferenceInvalidError(reason="processing_original_file_evidence_required")
                    target = ResourceVersionTarget(
                        file_id=claimed.item.file_id,
                        document_id=claimed.item.document_id,
                        version_id=claimed.item.version_id,
                    )
                    actual = await scope.aload_scope(
                        session, space_id, targets=[target.model_dump(mode="json")], for_update=True
                    )
                    if len(actual) != 1 or actual[0].parent_id != claimed.item.expected_parent_id:
                        raise KnowledgeProcessingConflictError(reason="processing_file_scope_changed")
                    if actual[0].status in {1, 4, 5}:
                        raise KnowledgeProcessingConflictError(reason="processing_file_state_not_ready")
                    # A later safety rejection remains rejected. Record the
                    # failed item under this lease without changing file state.
                    if actual[0].status == 7:
                        await owner.jobs.acomplete_item(
                            session,
                            claimed.lease,
                            configuration=current.configuration,
                            succeeded=False,
                            error_code=KnowledgeFileFailedError.Code,
                        )
                        await session.commit()
                        continue
                    if not reset.prepared and claimed.item.id != reset.anchor_item_id:
                        raise KnowledgeProcessingConflictError(reason="processing_reset_anchor_changed")
                    audit_user_id = reference["actor_user_id"]
                    expectations = {
                        "space_id": space_id,
                        "invoke_user_id": audit_user_id,
                        "operation_id": operation_id,
                        "expected_model_config_revision": current.configuration.model_config_revision,
                        "expected_index_generation": current.configuration.index_generation,
                    }
                    await session.commit()
                if not reset.prepared:
                    await asyncio.to_thread(reset_processing_target, **expectations)
                    async with get_async_db_session() as session:
                        marked = await owner.jobs.amark_target_reset(session, claimed.lease)
                        result = _summary(await owner.jobs.aget(session, job_id))
                        await session.commit()
                        if not marked:
                            return result
                try:
                    outcome = await asyncio.to_thread(PROCESSING_HANDLERS[kind], target.file_id, **expectations)
                    succeeded, count = outcome.succeeded, outcome.chunk_count
                except BaseErrorCode:
                    raise
                except Exception:
                    logger.exception("Knowledge file rebuild failed job={} file={}", job_id, target.file_id)
                    succeeded, count = False, 0
            # Credential and business permission are current again before SQL
            # result writes. No external operation is hidden inside this TX.
            async with _actor(reference, proof.tenant_id, space_id) as identity:
                async with get_async_db_session() as session:
                    await scope._attempt(session, job_id, owner.jobs)
                    current = await owner.aread_current(session, space_id, identity=identity)
                    guarded = await owner.jobs._guard_item(session, claimed.lease, current.configuration)
                    if guarded is not None:
                        checkpoint = {**guarded[1].checkpoint, "chunk_count": count}
                        await owner.jobs.asave_checkpoint(
                            session,
                            claimed.lease,
                            configuration=current.configuration,
                            step="embedding_written" if succeeded else "embedding_failed",
                            checkpoint=checkpoint,
                        )
                    completed = await scope.acomplete_file(
                        session,
                        claimed.lease,
                        jobs=owner.jobs,
                        succeeded=succeeded,
                        error_code=None if succeeded else KnowledgeFileFailedError.Code,
                    )
                    job = await owner.jobs.aget(session, job_id)
                    result = _summary(job)
                    revision = job.revision
                    await session.commit()
                    if not completed:
                        return result
    except BaseErrorCode as error:
        logger.opt(exception=True).warning("Knowledge processing rejected job={} code={}", job_id, error.Code)
        return await _failed(owner, job_id, revision, lease, error.Code)
    except Exception:
        logger.exception("Knowledge processing failed job={}", job_id)
        return await _failed(owner, job_id, revision, lease, KnowledgeFileFailedError.Code)


async def _dispatch_pending_processing_jobs() -> int:
    owner = _new_owner()
    count = 0
    for tenant_id in await _active_tenant_ids():
        with tenant_execution_scope(tenant_id):
            after = None
            while True:
                async with get_async_db_session() as session:
                    candidates = await owner.jobs.adispatch_candidates(session, now=owner.jobs._now(), after_id=after)
                if not candidates:
                    break
                for row in candidates:
                    published, error_code = False, None
                    try:
                        execute_processing_job.apply_async(
                            kwargs={"job_id": row.job_id, "expected_dispatch_revision": row.revision},
                            headers={"tenant_id": row.tenant_id},
                            queue="knowledge_celery",
                        )
                        published = True
                        count += 1
                    except Exception:
                        error_code = KnowledgeFileFailedError.Code
                        logger.exception("Knowledge processing publish failed tenant={} job={}", tenant_id, row.job_id)
                    async with get_async_db_session() as session:
                        await owner.jobs.arecord_dispatch(
                            session,
                            row.job_id,
                            expected_revision=row.revision,
                            published=published,
                            error_code=error_code,
                            next_at=owner.jobs._now() + timedelta(seconds=60),
                        )
                        await session.commit()
                    after = row.job_id
    return count


@bisheng_celery.task(name=EXECUTE_TASK, acks_late=True)
def execute_processing_job(job_id: str, expected_dispatch_revision: int):
    return run_async_task(lambda: _execute_processing_job(job_id, expected_dispatch_revision))


@bisheng_celery.task(name=SCAN_TASK, acks_late=True)
def dispatch_pending_processing_jobs():
    return run_async_task(_dispatch_pending_processing_jobs)
