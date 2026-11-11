"""Move-only runner on the existing processing task, queue and native ledger."""

import asyncio
from dataclasses import asdict, fields
from time import monotonic

from loguru import logger

from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError, ResourceReferenceInvalidError
from bisheng.core.context.background_execution import get_current_background_task
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.knowledge.application.move_processing_access import get_move_owner as get_move_owner
from bisheng.knowledge.application.processing_identity import restore_processing_actor
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.worker.knowledge.move_worker import (
    MoveIndexCheckpoint,
    MoveIndexResult,
    MoveMetadataPolicy,
    apply_move_index_item,
)


def _stopped():
    raise KnowledgeProcessingConflictError(reason="move_execution_stopped")


async def _current(owner, job_id):
    async with owner._session() as session:
        return await owner._job(session, job_id)


async def _summary(owner, job_id):
    job, _ = await _current(owner, job_id)
    return {"job_id": job.id, "state": job.state}


class _Checkpoints:
    def __init__(self, owner, lease):
        self.owner, self.lease = owner, lease

    async def aload(self):
        current = await self.owner.aguard_item(self.lease)
        if current is None:
            _stopped()
        value = dict(current.checkpoint)
        # The native guard has already checked the private logical marker.
        value.pop("logical_move", None)
        if not value:
            return None
        if set(value) != {field.name for field in fields(MoveIndexCheckpoint)}:
            raise ResourceReferenceInvalidError(reason="move_checkpoint_closed_shape_required")
        return MoveIndexCheckpoint(**value)

    async def asave(self, checkpoint):
        if type(checkpoint) is not MoveIndexCheckpoint:
            raise ResourceReferenceInvalidError(reason="move_checkpoint_typed_required")
        if not await self.owner.asave_item_checkpoint(self.lease, step=checkpoint.step, checkpoint=asdict(checkpoint)):
            _stopped()
        # The Owner has committed this ACK before the adapter may clear source.
        return None


async def _execute_item(owner, lease):
    current = await owner.aguard_item(lease)
    if current is None:
        _stopped()
    _, reference = await _current(owner, lease.job.job_id)
    policy = current.snapshot["metadata_policy"]
    renewed_at = monotonic()

    async def guard():
        nonlocal renewed_at
        if monotonic() - renewed_at >= 15:
            if not await owner.arenew_attempt(lease.job) or not await owner.arenew_item(lease):
                _stopped()
            renewed_at = monotonic()
        if await owner.aguard_item(lease) is None:
            _stopped()

    async with restore_processing_actor(reference, tenant_id=get_current_tenant_id()):
        result = await apply_move_index_item(
            operation_id=lease.job.job_id,
            target=current.leaf.target,
            source=Knowledge(**current.source),
            destination=Knowledge(**current.destination),
            invoke_user_id=reference["actor_user_id"],
            metadata_policy=MoveMetadataPolicy(tuple(policy["retained_fields"]), tuple(policy["removed_fields"])),
            guard=guard,
            checkpoints=_Checkpoints(owner, lease),
        )
    if (
        type(result) is not MoveIndexResult
        or type(result.file_id) is not int
        or result.file_id != current.leaf.target.file_id
    ):
        raise ResourceReferenceInvalidError(reason="move_index_typed_result_required")
    if not await owner.acomplete_item(
        lease,
        **{
            name: getattr(result, name)
            for name in ("source_count", "milvus_count", "es_count", "source_digest", "target_payload_digest")
        },
    ):
        _stopped()


async def execute_move_job(job_id, expected_dispatch_revision, *, owner, proof):
    from bisheng.worker.knowledge.processing_jobs import EXECUTE_TASK

    if (
        proof is None
        or proof is not get_current_background_task()
        or proof.task_name != EXECUTE_TASK
        or proof.tenant_id != get_current_tenant_id()
    ):
        raise ResourceReferenceInvalidError(reason="processing_actual_worker_required")
    lease = None
    try:
        lease = await owner.astart_attempt(job_id, expected_dispatch_revision=expected_dispatch_revision)
        if lease is None:
            return await _summary(owner, job_id)
        logical = await owner.aensure_logical(lease)
        if logical is None or logical.state != "running":
            return await _summary(owner, job_id)
        while True:
            item = await owner.aclaim_item(lease)
            if item is None:
                await owner.afinalize_attempt(lease)
                return await _summary(owner, job_id)
            try:
                await _execute_item(owner, item)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.exception("Move index item failed job={} item={}", job_id, item.item_id)
                code = error.Code if isinstance(error, BaseErrorCode) else ResourceReferenceInvalidError.Code
                if not await owner.afail_item(item, error_code=code):
                    return await _summary(owner, job_id)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("Move attempt failed job={}", job_id)
        job, _ = await _current(owner, job_id)
        code = error.Code if isinstance(error, BaseErrorCode) else ResourceReferenceInvalidError.Code
        await owner.afail_attempt(job_id, expected_job_revision=job.revision, error_code=code, lease=lease)
        return await _summary(owner, job_id)
