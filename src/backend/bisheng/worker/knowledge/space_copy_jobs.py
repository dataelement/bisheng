"""Actual copy execution on the existing processing task and Beat dispatch."""

import asyncio
from time import monotonic

from loguru import logger

from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError, ResourceReferenceInvalidError
from bisheng.core.context.background_execution import get_current_background_task
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.knowledge.application.space_copy_owner import SpaceCopyOwner
from bisheng.knowledge.domain.schemas.processing_diagnostics import failure_reason_from_error
from bisheng.worker.knowledge.space_copy_worker import apply_space_copy_item


async def execute_copy_job(job_id, revision, *, proof, owner=None):
    from bisheng.worker.knowledge.processing_jobs import EXECUTE_TASK

    if (
        proof is None
        or proof is not get_current_background_task()
        or proof.task_name != EXECUTE_TASK
        or proof.tenant_id != get_current_tenant_id()
    ):
        raise ResourceReferenceInvalidError(reason="processing_actual_worker_required")
    owner, lease = owner or SpaceCopyOwner(), None

    async def summary():
        job, _ = await owner.aread(job_id)
        return {"job_id": job.id, "state": job.state}

    try:
        lease = await owner.astart(job_id, revision)
        if lease is None:
            return await summary()
        job, _ = await owner.aread(job_id, full=True)
        mapping = job.parameters["mapping"]["files"]
        from bisheng.knowledge.domain.repositories.space_copy_repository import object_names

        object_map = job.parameters.get("object_map")
        if object_map is None:
            # Old accepted jobs retain their original confirmation.
            _, payload, _, _ = await owner._logical(job.space_id, job_id)
            object_map = {}
            for row in payload["scope"]["files"]:
                if row["file_type"] == 1:
                    names = object_names(row, job.space_id, mapping[str(row["id"])])
                    object_map.update({row[key]: value for key, value in names.items() if value and row[key]})
        while True:
            phase = "copy_input_failed"
            claimed = await owner.aclaim(lease)
            if claimed is None:
                await owner.afinalize(lease)
                return await summary()
            try:
                current = await owner.aguard(claimed.lease)
                if current is None:
                    raise KnowledgeProcessingConflictError(reason="copy_execution_stopped")
                phase = "copy_index_failed" if current.input_state is not None else "copy_input_failed"
                renewed = monotonic()

                item_lease = claimed.lease

                async def guard(item_lease=item_lease):
                    nonlocal renewed
                    refresh = monotonic() - renewed >= 15
                    if await owner.aguard(item_lease, renew=refresh) is None:
                        raise KnowledgeProcessingConflictError(reason="copy_execution_stopped")
                    if refresh:
                        renewed = monotonic()

                async def input_ready(value, item_lease=item_lease):
                    nonlocal phase
                    await owner.asave_input(item_lease, value)
                    phase = "copy_index_failed"

                _, reference = await owner.aread(job_id)
                from bisheng.knowledge.application.move_processing_admission import identity

                async with identity(reference, required_action="upload_file"):
                    async with owner.input_writer(item_lease):
                        result = await apply_space_copy_item(
                            operation_id=job_id,
                            snapshot=current.snapshot,
                            file_ids={
                                **mapping,
                                str(current.snapshot["source_file"]["id"]): current.snapshot["target_file"]["id"],
                            },
                            object_map=object_map,
                            invoke_user_id=reference["actor_user_id"],
                            guard=guard,
                            input_state=current.input_state,
                            input_ready=input_ready,
                            record_input=lambda key, item_lease=item_lease: owner.arecord_input(item_lease, key),
                        )
                if not await owner.acomplete(claimed.lease, result=result):
                    return await summary()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.exception("Space copy item failed job={} item={}", job_id, claimed.item.id)
                code = error.Code if isinstance(error, BaseErrorCode) else ResourceReferenceInvalidError.Code
                if not await owner.acomplete(
                    claimed.lease, error_code=code, failure_reason=failure_reason_from_error(error) or phase
                ):
                    return await summary()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("Space copy attempt failed job={}", job_id)
        job, _ = await owner.aread(job_id)
        code = error.Code if isinstance(error, BaseErrorCode) else ResourceReferenceInvalidError.Code
        await owner.afail(
            job_id,
            job.revision,
            lease=lease,
            error_code=code,
            failure_reason=failure_reason_from_error(error) or "copy_initialization_failed",
        )
        return await summary()
