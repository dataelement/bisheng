"""Shared actual P1/K1/Job composition for native move execution tests."""

from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from types import SimpleNamespace

import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.knowledge.domain.repositories.move_job_ready_repository import MoveJobReadyRepository
from bisheng.knowledge.domain.repositories.processing_job_repository import ProcessingJobRepository
from bisheng.knowledge.domain.schemas.processing_job_acceptance import ProcessingConfiguration
from bisheng.permission.application.identity import PermissionActor
from bisheng.permission.domain.models import AuthorizationModelRelease, PermissionCatalogRelease
from bisheng.permission.domain.repositories.move_projection_repository import MoveProjectionExpectation
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.worker.knowledge.move_worker import MoveIndexCheckpoint, MoveMetadataPolicy, _scope
from test.knowledge_unification.test_move_job_reservation import create, jobs
from test.knowledge_unification.test_move_projection import compose

CONFIG = ProcessingConfiguration(4, "generation-4")


async def pipeline(moving, accepted, monkeypatch, *, zero=None, count=1):
    if count > 1:
        async with AsyncSession(moving.engine) as session:
            await session.execute(
                sa.insert(File.__table__),
                [
                    {
                        "id": 1000 + n,
                        "tenant_id": 101,
                        "knowledge_id": 10,
                        "file_name": str(n),
                        "file_type": 1,
                        "file_level_path": "/50",
                        "level": 1,
                        "status": 2,
                    }
                    for n in range(count - 1)
                ],
            )
            await session.execute(
                sa.insert(Version.__table__),
                [
                    {
                        "id": 20000 + n,
                        "document_id": 80,
                        "knowledge_file_id": 1000 + n,
                        "version_no": n + 3,
                        "is_primary": False,
                    }
                    for n in range(count - 1)
                ],
            )
            await session.commit()
    confirmed = await accepted(zero=zero)
    move, cutover = jobs(moving)
    job = (await create(moving, confirmed.args, move)).job
    clock = [datetime.now()]
    cutover.clock = lambda: clock[0]
    ready = MoveJobReadyRepository(move_jobs=move, clock=lambda: clock[0])

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(moving.engine, expire_on_commit=False) as session:
            yield session

    expectations = []
    for change in confirmed.scope.parent_changes:
        common = {
            "tenant_id": 101,
            "resource_type": change.resource_type,
            "resource_id": str(change.resource_id),
            "resource_version": change.expected_permission_version,
            "context_version": confirmed.scope.scope_digest,
        }
        before = VerifiedPermissionTarget.from_business_service(
            **common, parent_type=change.old_parent_type, parent_id=str(change.old_parent_id)
        )
        after = VerifiedPermissionTarget.from_business_service(
            **common, parent_type=change.new_parent_type, parent_id=str(change.new_parent_id)
        )
        expectations.append(
            MoveProjectionExpectation(
                job.id,
                101,
                change.resource_type,
                str(change.resource_id),
                before,
                after,
                change.mode,
                change.expected_permission_version,
                confirmed.scope.changes_digest,
                (7,),
            )
        )
    p1 = await compose(SimpleNamespace(engine=moving.engine, sessions=sessions), monkeypatch, tuple(expectations))
    async with moving.engine.begin() as connection:
        await connection.execute(
            sa.insert(AuthorizationModelRelease),
            {
                "id": 1,
                "environment": "test",
                "store_id": "actual-store",
                "model_id": "actual-model",
                "model_version": "f048",
                "model_checksum": "a" * 64,
                "required_relations_checksum": "b" * 64,
                "openfga_version": "1",
                "status": "ACTIVE",
            },
        )
        await connection.execute(
            sa.insert(PermissionCatalogRelease),
            {
                "id": 1,
                "release_key": "current",
                "version": 1,
                "status": "CURRENT",
                "write_fenced": False,
                "required_authorization_model_release_id": 1,
                "draft_owner_id": 7,
                "idempotency_key": "catalog",
                "checksum": "c" * 64,
            },
        )
    from bisheng.knowledge.domain.repositories.move_execution_repository import MoveExecutionRepository

    cutover.projection_verifier = p1.bridge
    execution = MoveExecutionRepository(move_jobs=move, move_ready=ready)
    repo = ProcessingJobRepository(move_jobs=move, move_ready=ready, move_execution=execution, clock=lambda: clock[0])
    async with sessions() as session, session.begin():
        lease = await repo.aclaim(session, job.id, configuration=CONFIG, _move=True)
        assert lease is not None  # Actual composition permits leasing before logical ready.
        assert await execution.avalidate_attempt(session, lease=lease, jobs=repo) is not None
    assert (
        await p1.bridge.aexecute_or_resume(
            job_id=job.id, changes=tuple(expectations), actor=PermissionActor(user_id=7, current_tenant_id=101)
        )
    ).complete
    return SimpleNamespace(
        job_id=job.id,
        confirmed=confirmed,
        move=move,
        cutover=cutover,
        ready=ready,
        repo=repo,
        execution=execution,
        clock=clock,
        lease=lease,
        sessions=sessions,
        bridge=p1.bridge,
        expectations=tuple(expectations),
    )


async def logical(session, built):
    prepared = await built.cutover.aprepare_cutover(session, job_id=built.job_id, lease=built.lease)
    evidence = await built.bridge.arequire_finalized(session, job_id=built.job_id, expectations=built.expectations)
    return await built.cutover.aapply_logical(session, prepared=prepared, projection_evidence=evidence)


async def mark(session, built, receipt):
    return await built.repo.amark_move_ready(session, logical_receipt=receipt, lease=built.lease)


async def item_evidence(session, built):
    return await built.bridge.arequire_finalized(session, job_id=built.job_id, expectations=built.expectations)


async def complete_move(session, built, lease, *, count=0):
    evidence = await item_evidence(session, built)
    snapshot = await built.execution.aread_item(session, job_id=built.job_id, item_id=lease.item_id)
    policy = snapshot.snapshot["metadata_policy"]
    binding = _scope(
        built.job_id,
        snapshot.leaf.target,
        Knowledge(**snapshot.source),
        Knowledge(**snapshot.destination),
        7,
        MoveMetadataPolicy(tuple(policy["retained_fields"]), tuple(policy["removed_fields"])),
    )
    checkpoint = MoveIndexCheckpoint(
        **binding,
        step="move_source_cleaned",
        source_count=count,
        source_digest="1" * 64,
        target_milvus_count=count,
        target_es_count=count,
        target_payload_digest="2" * 64,
    )
    assert await built.repo.asave_checkpoint(
        session,
        lease,
        configuration=CONFIG,
        step=checkpoint.step,
        checkpoint=asdict(checkpoint),
        _move=True,
        move_projection_evidence=evidence,
    )
    return await built.execution.acomplete_item(
        session,
        lease,
        jobs=built.repo,
        projection_evidence=evidence,
        source_count=count,
        milvus_count=count,
        es_count=count,
        source_digest=checkpoint.source_digest,
        target_payload_digest=checkpoint.target_payload_digest,
    )
