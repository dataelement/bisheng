"""Real prepared deletion is not an ordinary cleanup task during migration."""

import socket
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_tasks import QueuedTaskInventoryReader
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from bisheng.knowledge.domain.services.knowledge_space_direct_delete_service import KnowledgeSpaceDirectDeleteService
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification.test_direct_delete_reference_query import SqlStatus
from test.knowledge_unification.test_kn_delete_plan import application as application
from test.knowledge_unification.test_kn_delete_plan import context as context
from test.knowledge_unification.test_kn_delete_plan import db as db
from test.knowledge_unification.test_kn_delete_plan import deletion_tenant as deletion_tenant
from test.knowledge_unification.test_kn_delete_plan import service as service


class NativeRedis:
    async def scan(self, cursor=0, *, match, count):
        assert count == 200
        return 0, []

    async def type(self, key):
        return b"none"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network")))


async def test_real_prepared_empty_clear_is_emitted_as_ordinary_task_and_epoch_change_breaks_retry(
    application, context, monkeypatch
):
    plan = await application.aprecheck(identity=application.user, space_id=2, operation="knowledge_space_clear")
    assert plan.can_execute and not any(plan.impact["source_counts"].values())
    request = ProcessingCreateRequest(
        confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest, idempotency_key="real-prepared-crash"
    )
    with monkeypatch.context() as mp:
        mp.setattr(
            KnowledgeSpaceDirectDeleteService,
            "purge",
            AsyncMock(side_effect=OSError("native crash after durable prepare")),
        )
        with pytest.raises(OSError):
            await application.aconfirm(identity=application.user, space_id=2, request=request)
    async with context.db.sessions() as session, session.begin():
        job = await session.get(KnowledgeSpaceDeleteJob, plan.confirmation_id)
        frozen = await session.get(KnowledgeOperationPlan, plan.confirmation_id)
        assert job.business_phase == "prepared" and job.state == "PENDING"
        assert frozen.source_revisions["epoch"] == 1
        assert not (await session.execute(sa.select(ResourceReferenceTombstone.id))).all()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            _ = [
                r
                async for r in QueuedTaskInventoryReader(session, redis_connection=NativeRedis()).aiter_facts(
                    tenant_ids=(101, 202)
                )
            ]
    original = SqlStatus.aget_global_status

    async def next_epoch(self, version):
        return replace(await original(self, version), coverage_epoch=2)

    monkeypatch.setattr(SqlStatus, "aget_global_status", next_epoch)
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await application.aconfirm(identity=application.user, space_id=2, request=request)
    print("ACTUAL_RESUME_REJECT", caught.value.kwargs)
    assert caught.value.kwargs["reason"] == "knowledge_delete_impact_changed"


async def test_actual_sql_finalized_cleanup_is_allowed_and_does_not_revalidate_old_epoch(
    application, context, monkeypatch
):
    failed = False

    async def purge(step, job):
        nonlocal failed
        if step == "es" and not failed:
            failed = True
            raise OSError("native ES cleanup failure after SQL finalized")

    application.purge_step = purge
    plan = await application.aprecheck(identity=application.user, space_id=2, operation="knowledge_space_clear")
    request = ProcessingCreateRequest(
        confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest, idempotency_key="real-finalized"
    )
    with pytest.raises(OSError):
        await application.aconfirm(identity=application.user, space_id=2, request=request)
    async with context.db.sessions() as session, session.begin():
        job = await session.get(KnowledgeSpaceDeleteJob, plan.confirmation_id)
        assert job.business_phase == "finalized" and job.state == "PENDING" and job.completed_steps == ["fga", "minio"]
        records = [
            r
            async for r in QueuedTaskInventoryReader(session, redis_connection=NativeRedis()).aiter_facts(
                tenant_ids=(101, 202)
            )
        ]
        assert any(r.data.get("task_id") == job.id for r in records)
    original = SqlStatus.aget_global_status

    async def next_epoch(self, version):
        return replace(await original(self, version), coverage_epoch=2)

    monkeypatch.setattr(SqlStatus, "aget_global_status", next_epoch)
    assert (await application.aconfirm(identity=application.user, space_id=2, request=request))["state"] == "succeeded"


@pytest.mark.parametrize(
    "operation,phase", [(None, None), ("knowledge_space_clear", "finalized"), ("knowledge_file_delete", "finalized")]
)
async def test_legacy_and_finalized_task_classifications_still_pass_actual_guard(
    application, context, operation, phase
):
    from bisheng.knowledge.domain.repositories.unification_task_repository import UnificationTaskRepository

    async with context.db.sessions() as session, session.begin():
        session.add(
            KnowledgeSpaceDeleteJob(
                tenant_id=101,
                space_id=2,
                applicant_user_id=7,
                operation_type=operation,
                business_phase=phase,
                manifest={},
            )
        )
    async with context.db.sessions() as session, session.begin():
        await UnificationTaskRepository().avalidate_migration_idle(session)


@pytest.mark.parametrize(
    "operation,phase",
    [
        (None, "prepared"),
        ("unknown", "finalized"),
        ("knowledge_space_clear", None),
        ("knowledge_space_clear", "unknown"),
    ],
)
async def test_unknown_new_or_half_phase_never_borrows_legacy_cleanup_semantics(application, context, operation, phase):
    from bisheng.knowledge.domain.repositories.unification_task_repository import UnificationTaskRepository

    async with context.db.sessions() as session, session.begin():
        session.add(
            KnowledgeSpaceDeleteJob(
                tenant_id=101,
                space_id=2,
                applicant_user_id=7,
                operation_type=operation,
                business_phase=phase,
                manifest={},
            )
        )
    async with context.db.sessions() as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await UnificationTaskRepository().avalidate_migration_idle(session)
