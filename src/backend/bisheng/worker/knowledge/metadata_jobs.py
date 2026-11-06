"""Leased metadata indexing through original actors and exact native guards."""

import json
from dataclasses import replace

from loguru import logger

from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeFileFailedError, KnowledgeProcessingObsoleteError
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.model_reference_read import get_knowledge_model_read_runtime
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.repositories.processing_job_repository import ProcessingConfiguration
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.worker.knowledge.metadata_worker import apply_metadata_index_item


class _Stopped(KnowledgeProcessingObsoleteError):
    def __init__(self, result):
        super().__init__()
        self.result = result


def _summary(job):
    return {"job_id": job.id, "state": job.state}


async def execute_metadata_job(job_id, expected_dispatch_revision, *, owner, proof):
    # Import after the common task module has finished registration. This is
    # the same original credential/authority restoration used by other kinds.
    from bisheng.worker.knowledge.processing_jobs import _actor

    jobs, execution = owner.jobs, owner.metadata.execution
    lease, item_lease, revision = None, None, expected_dispatch_revision
    async with get_async_db_session() as session:
        job = await jobs.aget_execution(session, job_id)
        if job.kind != "metadata_schema_change" or job.revision != revision or job.state not in {"accepted", "running"}:
            return _summary(job)
        reference = await jobs.alatest_retry_actor(session, job_id)
        space_id = job.space_id

    async def configuration(session):
        if not session.in_transaction():
            await session.begin()
        actual = await execution.aread_configuration(session, space_id)
        return ProcessingConfiguration(
            actual.model_config_revision,
            actual.index_generation,
            metadata_schema_revision=actual.metadata_schema_revision,
            metadata_schema_digest=actual.metadata_schema_digest,
        )

    async def admitted_knowledge(session, identity):
        runtime = await get_knowledge_model_read_runtime()
        admitted = await runtime.arequire(
            space_id, login_user=None if isinstance(identity, OpenApiPrincipal) else identity, session=session
        )
        return Knowledge(**json.loads(admitted.read.snapshot.payload_json)["knowledge"])

    async def stopped(session):
        result = _summary(await jobs.aget_execution(session, job_id))
        # A rejected configuration is durable obsolete state; raising before
        # this commit would silently undo it. Lost leases never mutate peers.
        await session.commit()
        raise _Stopped(result)

    async def guarded(session, identity):
        nonlocal lease, item_lease
        current = await configuration(session)
        renewed = await jobs.arenew(session, lease, configuration=current)
        if renewed is None:
            await stopped(session)
        lease = renewed
        item_lease = await jobs.arenew_item(session, replace(item_lease, job=lease), configuration=current)
        if item_lease is None:
            await stopped(session)
        pair = await jobs._guard_item(session, item_lease, current)
        if pair is None:
            await stopped(session)
        job, item = pair
        snapshot = await execution.aread_item(session, job, item)
        knowledge = await admitted_knowledge(session, identity)
        return job, item, snapshot, knowledge, current

    async def guard():
        async with _actor(reference, proof.tenant_id, space_id) as identity:
            async with get_async_db_session() as session:
                await guarded(session, identity)
                await session.commit()

    try:
        async with _actor(reference, proof.tenant_id, space_id) as identity:
            async with get_async_db_session() as session:
                current = await configuration(session)
                await admitted_knowledge(session, identity)
                lease = await jobs.aclaim(
                    session, job_id, configuration=current, expected_job_revision=expected_dispatch_revision
                )
                job = await jobs.aget_execution(session, job_id)
                result, revision = _summary(job), job.revision
                await session.commit()
                if lease is None:
                    return result
        while True:
            async with _actor(reference, proof.tenant_id, space_id) as identity:
                async with get_async_db_session() as session:
                    current = await configuration(session)
                    lease = await jobs.arenew(session, lease, configuration=current)
                    if lease is None:
                        await stopped(session)
                    await admitted_knowledge(session, identity)
                    claimed = await jobs.aclaim_next_item(session, lease, configuration=current)
                    if claimed is None:
                        final = await jobs.afinalize(session, lease, configuration=current)
                        result = _summary(final if final is not None else await jobs.aget_execution(session, job_id))
                        await session.commit()
                        return result
                    item_lease = claimed.lease
                    job, item, snapshot, knowledge, _ = await guarded(session, identity)
                    await session.commit()
            try:
                outcome = await apply_metadata_index_item(
                    knowledge=knowledge,
                    invoke_user_id=reference["actor_user_id"],
                    file_id=snapshot.target.file_id,
                    affected_fields=snapshot.affected_fields,
                    after_values=snapshot.after_values,
                    guard=guard,
                )
            except KnowledgeFileFailedError as error:
                logger.opt(exception=True).warning("Metadata index item failed job={} file={}", job_id, item.file_id)
                async with _actor(reference, proof.tenant_id, space_id) as identity:
                    async with get_async_db_session() as session:
                        await guarded(session, identity)
                        current = await configuration(session)
                        if not await jobs.acomplete_item(
                            session, item_lease, configuration=current, succeeded=False, error_code=error.Code
                        ):
                            await stopped(session)
                        await session.commit()
                continue
            async with _actor(reference, proof.tenant_id, space_id) as identity:
                async with get_async_db_session() as session:
                    job, item, _, _, current = await guarded(session, identity)
                    if not await jobs.asave_checkpoint(
                        session,
                        item_lease,
                        configuration=current,
                        step="metadata_index_written",
                        checkpoint={
                            **item.checkpoint,
                            "milvus_count": outcome.milvus_count,
                            "es_count": outcome.es_count,
                        },
                    ):
                        await stopped(session)
                    if not await execution.awrite_values(session, job, item, lease=item_lease):
                        await stopped(session)
                    await session.commit()
    except _Stopped as error:
        return error.result
    except BaseErrorCode as error:
        logger.opt(exception=True).warning("Metadata processing rejected job={} code={}", job_id, error.Code)
        error_code = error.Code
    except Exception:
        logger.exception("Metadata processing failed job={}", job_id)
        error_code = KnowledgeFileFailedError.Code
    # Failure processing requires real worker proof but cannot depend on the
    # now-revoked actor. The repository locks the actual root and current lease.
    async with get_async_db_session() as session:
        failed = await jobs.afail_attempt(
            session, job_id, expected_job_revision=revision, lease=lease, error_code=error_code
        )
        result = _summary(failed if failed is not None else await jobs.aget_execution(session, job_id))
        await session.commit()
        return result
