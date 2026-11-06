"""T608: durable confirmation plans use the caller's real SQL transaction."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanChangedError,
    KnowledgeOperationPlanExpiredError,
)
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.repositories.operation_plan_repository import OperationPlanRepository
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget


@pytest.fixture
def plan_tenant(tenant_context):
    tenant_context(101)


@pytest.fixture
async def plans(plan_tenant):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn, tables=[Knowledge.__table__, KnowledgeOperationPlan.__table__]
            )
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Knowledge(id=1, tenant_id=101, user_id=11, name="unchanged", type=3))
        await session.commit()
        yield session
    await engine.dispose()


@pytest.fixture
def clock():
    return [datetime(2026, 11, 6, 9, 0)]


@pytest.fixture
def repository(clock):
    return OperationPlanRepository(clock=lambda: clock[0])


def actor():
    return {"tenant_id": 101, "actor_user_id": 11, "credential_reference": {"kind": "web_session", "user_id": 11}}


async def create(repository, session, clock, **overrides):
    values = {
        "operation": "embedding_rebuild",
        "space_id": 1,
        "actor_reference": actor(),
        "targets": [ResourceVersionTarget(file_id=8, document_id=18, version_id=28)],
        "target_revisions": {"model": 7, "index_generation": "generation-7"},
        "source_revisions": {"document:18": 2},
        "parameters": {"rebuild": "existing_chunks"},
        "impact": {"retrieval_paused": True},
        "expires_at": clock[0] + timedelta(minutes=5),
    }
    return await repository.acreate(session, **{**values, **overrides})


async def load(repository, session, plan, **overrides):
    values = {
        "space_id": 1,
        "operation": "embedding_rebuild",
        "actor_reference": actor(),
        "plan_digest": plan.plan_digest,
    }
    return await repository.aget_for_execution(session, plan.confirmation_id, **{**values, **overrides})


async def test_precheck_persists_only_plan_and_joins_owner_transaction(plans, repository, clock):
    plan = await create(repository, plans, clock)
    assert plan.can_execute and plan.check_complete
    assert [(item.id, item.type) for item in plan.valid_items] == [(8, "file")]
    row = await load(repository, plans, plan)
    assert row.actor_user_id == 11 and row.tenant_id == 101
    assert row.target_manifest == [{"file_id": 8, "document_id": 18, "version_id": 28}]
    assert row.operation_id is row.consumed_at is None
    space = await plans.get(Knowledge, 1)
    assert space.name == "unchanged" and space.model_transition is None
    await plans.rollback()
    assert not (await plans.exec(select(KnowledgeOperationPlan))).all()


async def test_empty_scope_cannot_be_executed(plans, repository, clock):
    plan = await create(repository, plans, clock, targets=[])
    assert plan.check_complete and not plan.can_execute and not plan.valid_items


@pytest.mark.parametrize(
    "override",
    [
        {"space_id": 2},
        {"operation": "file_resplit"},
        {"plan_digest": "0" * 64},
        {"actor_reference": {**actor(), "actor_user_id": 12}},
        {"actor_reference": {**actor(), "scope": "expanded"}},
    ],
)
async def test_plan_cannot_be_borrowed_by_other_actor_scope_or_command(plans, repository, clock, override):
    plan = await create(repository, plans, clock)
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await load(repository, plans, plan, **override)
    assert (await plans.get(KnowledgeOperationPlan, plan.confirmation_id)).operation_id is None


async def test_cross_tenant_plan_is_not_available(plans, repository, clock):
    plan = await create(repository, plans, clock)
    token = set_current_tenant_id(202)
    try:
        with pytest.raises(KnowledgeOperationPlanChangedError):
            await load(repository, plans, plan)
        with pytest.raises(KnowledgeOperationPlanChangedError):
            await repository.aconsume(
                plans, plan.confirmation_id, operation_id="job-a", expected_digest=plan.plan_digest
            )
    finally:
        current_tenant_id.reset(token)


async def test_unconsumed_plan_expiry_rejects_load_and_consume(plans, repository, clock):
    plan = await create(repository, plans, clock)
    clock[0] = plan.expires_at
    with pytest.raises(KnowledgeOperationPlanExpiredError):
        await load(repository, plans, plan)
    with pytest.raises(KnowledgeOperationPlanExpiredError):
        await repository.aconsume(plans, plan.confirmation_id, operation_id="job-a", expected_digest=plan.plan_digest)


async def test_consume_is_same_operation_idempotent_and_cannot_create_second_operation(plans, repository, clock):
    plan = await create(repository, plans, clock)
    await repository.aconsume(plans, plan.confirmation_id, operation_id="job-a", expected_digest=plan.plan_digest)
    await plans.commit()
    clock[0] += timedelta(minutes=10)
    await repository.aconsume(plans, plan.confirmation_id, operation_id="job-a", expected_digest=plan.plan_digest)
    row = await load(repository, plans, plan)
    assert row.operation_id == "job-a" and row.consumed_at is not None
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await repository.aconsume(plans, plan.confirmation_id, operation_id="job-b", expected_digest=plan.plan_digest)


async def test_consume_rolls_back_with_the_business_owner(plans, repository, clock):
    plan = await create(repository, plans, clock)
    await plans.commit()
    await repository.aconsume(plans, plan.confirmation_id, operation_id="job-a", expected_digest=plan.plan_digest)
    await plans.rollback()
    row = await load(repository, plans, plan)
    assert row.operation_id is row.consumed_at is None


async def test_frozen_payload_tamper_requires_new_confirmation(plans, repository, clock):
    plan = await create(repository, plans, clock)
    row = await load(repository, plans, plan)
    row.parameters = {"rebuild": "different"}
    await plans.flush()
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await load(repository, plans, plan)


async def test_request_payload_is_copied_and_target_order_is_canonical(plans, repository, clock):
    reference = actor()
    original = deepcopy(reference)
    plan = await create(
        repository,
        plans,
        clock,
        actor_reference=reference,
        targets=[
            ResourceVersionTarget(file_id=9, document_id=19, version_id=29),
            ResourceVersionTarget(file_id=8, document_id=18, version_id=28),
        ],
    )
    reference["scope"] = "changed_after_accept"
    row = await load(repository, plans, plan, actor_reference=original)
    assert "scope" not in row.actor_reference
    assert [item["file_id"] for item in row.target_manifest] == [8, 9]


@pytest.mark.parametrize("invalid", [{"tenant_id": 202}, {"actor_user_id": 0}, {"access_token": "never-persist"}])
async def test_invalid_identity_or_secret_is_rejected_before_writes(plans, repository, clock, invalid):
    with pytest.raises(ValueError):
        await create(repository, plans, clock, actor_reference={**actor(), **invalid})
    assert not (await plans.exec(select(KnowledgeOperationPlan))).all()
