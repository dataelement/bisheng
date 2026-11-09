"""Real prepared deletion is not an ordinary cleanup task during migration."""

from dataclasses import replace
from unittest.mock import AsyncMock
import socket
import pytest
import sqlalchemy as sa
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_tasks import QueuedTaskInventoryReader
from bisheng.knowledge.domain.services.knowledge_space_direct_delete_service import KnowledgeSpaceDirectDeleteService
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from test.knowledge_unification.test_kn_delete_plan import deletion_tenant as deletion_tenant, db as db, context as context, service as service, application as application
from test.knowledge_unification.test_direct_delete_reference_query import SqlStatus
class NativeRedis:
    async def scan(self, cursor=0, *, match, count):
        assert count == 200
        return 0, []
    async def type(self, key):
        return b'none'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket,'connect',lambda *a,**k: (_ for _ in ()).throw(AssertionError('no network')))

async def test_real_prepared_empty_clear_is_emitted_as_ordinary_task_and_epoch_change_breaks_retry(application,context,monkeypatch):
    plan=await application.aprecheck(identity=application.user,space_id=2,operation='knowledge_space_clear')
    assert plan.can_execute and not any(plan.impact['source_counts'].values())
    request=ProcessingCreateRequest(confirmation_id=plan.confirmation_id,plan_digest=plan.plan_digest,idempotency_key='real-prepared-crash')
    with monkeypatch.context() as mp:
        mp.setattr(KnowledgeSpaceDirectDeleteService,'purge',AsyncMock(side_effect=OSError('native crash after durable prepare')))
        with pytest.raises(OSError):
            await application.aconfirm(identity=application.user,space_id=2,request=request)
    async with context.db.sessions() as session,session.begin():
        job=await session.get(KnowledgeSpaceDeleteJob,plan.confirmation_id)
        frozen=await session.get(KnowledgeOperationPlan,plan.confirmation_id)
        assert job.business_phase=='prepared' and job.state=='PENDING'
        assert frozen.source_revisions['epoch']==1
        assert not (await session.execute(sa.select(ResourceReferenceTombstone.id))).all()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            _ = [r async for r in QueuedTaskInventoryReader(session,redis_connection=NativeRedis()).aiter_facts(tenant_ids=(101,202))]
    original=SqlStatus.aget_global_status
    async def next_epoch(self,version):
        return replace(await original(self,version),coverage_epoch=2)
    monkeypatch.setattr(SqlStatus,'aget_global_status',next_epoch)
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await application.aconfirm(identity=application.user,space_id=2,request=request)
    print('ACTUAL_RESUME_REJECT',caught.value.kwargs)
    assert caught.value.kwargs['reason']=='knowledge_delete_impact_changed'
