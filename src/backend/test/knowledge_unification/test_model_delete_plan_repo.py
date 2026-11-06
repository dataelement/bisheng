"""T655: model confirmation storage is independent of file/processing DTOs.

Hashes below are storage fixtures, not target authorization. Real target Owner
verification is exercised by test_llm_refs; execution must revalidate again.
"""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeOperationPlanExpiredError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.core.database import tenant_filter
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.domain.repositories.model_delete_plan_repository import ModelDeletePlanRepository
from bisheng.resource_reference.application.contracts import TargetKey
from test.knowledge_unification import test_llm_refs as impact_tests

model_owner_tenant = impact_tests.model_owner_tenant
removal_session = impact_tests.removal_session
impact = impact_tests.impact


@pytest.fixture
def plan_tenant(tenant_context, monkeypatch):
    tenant_context(101)
    names = tenant_filter._tenant_aware_tables | {"knowledge_operation_plan"}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    tenant_filter.register_tenant_filter_events()


@pytest.fixture
async def plans(plan_tenant):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda active: SQLModel.metadata.create_all(active, tables=[KnowledgeOperationPlan.__table__])
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest.fixture
def clock():
    return [datetime(2026, 11, 6, 9, 0)]


@pytest.fixture
def repository(clock):
    return ModelDeletePlanRepository(clock=lambda: clock[0])


def actor():
    return {
        "tenant_id": 101,
        "actor_user_id": 7,
        "management_tenant_id": 101,
        "credential_reference": {"kind": "web_session", "user_id": 7, "token_version": 3},
        "data_scope": "all",
    }


async def create(repository, session, clock, **overrides):
    values = {
        "operation": "model_update_server",
        "actor_reference": actor(),
        "command_digest": "c" * 64,
        "targets": [TargetKey("model", "11"), TargetKey("model", "2")],
        "target_revisions": {"model:2": "a" * 64, "model:11": "b" * 64, "server:1": "d" * 64},
        "inbound_digest": "e" * 64,
        "coverage_epoch": 9,
        "inventory_hash": "f" * 64,
        "expires_at": clock[0] + timedelta(minutes=5),
    }
    return await repository.acreate_model_delete_plan(session, **{**values, **overrides})


async def load(repository, session, confirmation, **overrides):
    values = {
        "confirmation_id": confirmation.confirmation_id,
        "operation": "model_update_server",
        "actor_reference": actor(),
        "command_digest": "c" * 64,
        "plan_digest": confirmation.plan_digest,
    }
    return await repository.aget_model_delete_plan_for_execution(session, **{**values, **overrides})


async def consume(repository, session, confirmation, **overrides):
    values = {
        "confirmation_id": confirmation.confirmation_id,
        "operation": "model_update_server",
        "operation_id": "deletion-1",
        "actor_reference": actor(),
        "command_digest": "c" * 64,
        "plan_digest": confirmation.plan_digest,
    }
    return await repository.aconsume_model_delete_plan(session, **{**values, **overrides})


@pytest.mark.parametrize("operation", ["model_update_server", "model_delete_server"])
async def test_model_manifest_and_all_frozen_hashes_persist_without_file_space_or_commit(
    plans, repository, clock, operation
):
    confirmation = await create(repository, plans, clock, operation=operation)
    row = await load(repository, plans, confirmation, operation=operation)
    assert row.space_id is None and row.operation == operation
    assert row.target_manifest == [
        {"target_type": "model", "target_id": "2"},
        {"target_type": "model", "target_id": "11"},
    ]
    assert row.parameters == {"command_digest": "c" * 64}
    assert row.impact == {"inbound_digest": "e" * 64, "coverage_epoch": 9, "inventory_hash": "f" * 64}
    assert row.source_revisions == {} and row.operation_id is None
    await plans.rollback()
    assert not (await plans.exec(select(KnowledgeOperationPlan))).all()


@pytest.mark.parametrize("field", ["operation", "actor", "command", "digest"])
async def test_get_and_consume_cannot_borrow_another_actor_command_or_operation(plans, repository, clock, field):
    confirmation = await create(repository, plans, clock)
    overrides = {
        "operation": {"operation": "model_delete_server"},
        "actor": {"actor_reference": {**actor(), "actor_user_id": 8}},
        "command": {"command_digest": "a" * 64},
        "digest": {"plan_digest": "0" * 64},
    }[field]
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await load(repository, plans, confirmation, **overrides)
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await consume(repository, plans, confirmation, **overrides)
    assert (await plans.get(KnowledgeOperationPlan, confirmation.confirmation_id)).operation_id is None


async def test_current_tenant_and_expiry_are_enforced(plans, repository, clock):
    confirmation = await create(repository, plans, clock)
    with tenant_execution_scope(202), pytest.raises(KnowledgeOperationPlanChangedError):
        await load(repository, plans, confirmation)
    clock[0] = confirmation.expires_at
    with pytest.raises(KnowledgeOperationPlanExpiredError):
        await load(repository, plans, confirmation)
    with pytest.raises(KnowledgeOperationPlanExpiredError):
        await consume(repository, plans, confirmation)


async def test_same_operation_consume_is_durable_idempotent_and_rollbackable(plans, repository, clock):
    confirmation = await create(repository, plans, clock)
    await plans.commit()
    await consume(repository, plans, confirmation)
    await plans.rollback()
    assert (await load(repository, plans, confirmation)).operation_id is None
    await consume(repository, plans, confirmation)
    await plans.commit()
    clock[0] = confirmation.expires_at + timedelta(days=1)
    await consume(repository, plans, confirmation)
    assert (await load(repository, plans, confirmation)).operation_id == "deletion-1"
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await consume(repository, plans, confirmation, operation_id="another-operation")


@pytest.mark.parametrize(
    "bad",
    [
        {"targets": [TargetKey("knowledge_file", "11")]},
        {"targets": [TargetKey("model", "11"), TargetKey("model", "11")]},
        {"target_revisions": {"server:1": "a" * 64}},
        {"target_revisions": {"server:1": "a" * 64, "server:2": "b" * 64, "model:2": "a" * 64, "model:11": "b" * 64}},
        {"target_revisions": {"model:2": "a" * 64, "model:11": "b" * 64, "model:99": "c" * 64, "server:1": "d" * 64}},
        {"command_digest": "not-a-hash"},
        {"coverage_epoch": 0},
        {"coverage_epoch": True},
        {"operation": "embedding_rebuild"},
    ],
)
async def test_manifest_revision_and_coverage_shape_cannot_be_guessed_or_mixed_with_processing(
    plans, repository, clock, bad
):
    with pytest.raises((ValueError, TypeError)):
        await create(repository, plans, clock, **bad)


@pytest.mark.parametrize(
    "extra",
    [
        {"trace_id": "request-1"},
        {"access_token": "secret"},
        {"api_key": "secret"},
        {"credential_reference": {"kind": "web_session", "user_id": 7, "token_version": 3, "Authorization": "secret"}},
        {"service_request": {"config": {"api_key": "secret"}}},
    ],
)
async def test_repo_rejects_trace_or_secrets_instead_of_silently_changing_authority(plans, repository, clock, extra):
    with pytest.raises(ValueError):
        await create(repository, plans, clock, actor_reference={**actor(), **extra})
    assert not (await plans.exec(select(KnowledgeOperationPlan))).all()


@pytest.mark.parametrize("field", ["target_revisions", "impact", "target_manifest"])
async def test_tampered_persisted_confirmation_is_not_executable(plans, repository, clock, field):
    confirmation = await create(repository, plans, clock)
    row = await plans.get(KnowledgeOperationPlan, confirmation.confirmation_id)
    changed = deepcopy(getattr(row, field))
    if isinstance(changed, dict):
        changed["tampered"] = True
    else:
        changed.append({"file_id": 1})
    setattr(row, field, changed)
    await plans.flush()
    with pytest.raises(KnowledgeOperationPlanChangedError):
        await load(repository, plans, confirmation)


async def test_empty_provider_still_requires_its_single_server_revision(plans, repository, clock):
    confirmation = await create(repository, plans, clock, targets=[], target_revisions={"server:1": "d" * 64})
    assert (await load(repository, plans, confirmation)).target_manifest == []


async def test_real_owner_inspection_revisions_enter_the_model_plan_unchanged(impact, repository, clock):
    session, service, _ = impact
    await session.run_sync(lambda active: KnowledgeOperationPlan.__table__.create(active.connection(), checkfirst=True))
    with impact_tests.actor() as identity:
        inspected = await service.ainspect_removed_models(
            session, identity=identity, server_id=1, retained_model_ids=(11,), delete_server=False
        )
    revisions = {f"model:{target.target_id}": revision for target, revision in inspected.target_revisions}
    revisions[f"server:{inspected.server_id}"] = inspected.server_revision
    confirmation = await repository.acreate_model_delete_plan(
        session,
        operation="model_update_server",
        actor_reference=actor(),
        command_digest="c" * 64,
        targets=inspected.targets,
        target_revisions=revisions,
        inbound_digest=inspected.inbound_digest,
        coverage_epoch=inspected.coverage_epoch,
        inventory_hash=inspected.inventory_hash,
        expires_at=clock[0] + timedelta(minutes=5),
    )
    stored = await load(repository, session, confirmation)
    assert stored.target_revisions == revisions
    assert stored.impact["inbound_digest"] == inspected.inbound_digest
    assert {item["target_id"] for item in stored.target_manifest} == {"12", "13", "14", "15"}
    await session.rollback()
