"""Model transition completion uses current business stage and one SQL/R2 commit.

覆盖 AC: AC-68, AC-71, AC-79, AC-87, AC-88, AC-89, AC-91, AC-92.
Actual Celery lifecycle hooks with an explicit header issue execution proof;
the current_task transport is isolated. No provider, broker or worker starts.
"""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel import Session

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as App
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.worker import tenant_context as workers
from test.knowledge_unification import test_kn_model_bindings as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business


@pytest.fixture
async def building(business, monkeypatch):
    await fixtures.seed(business)
    async with business.sessions() as session:
        change = await App.aprepare_model_change(session, 40, 12, login_user=business.user, operation_id="build-1")
        await App.aapply_model_change(session, change)
        await session.commit()
    original = next(row for row in fixtures.state(business)["knowledge"] if row["id"] == 40)
    sender = SimpleNamespace(
        name="bisheng.worker.knowledge.rebuild",
        request=SimpleNamespace(id="actual-build-task", headers={"tenant_id": 101}, called_directly=False),
    )
    monkeypatch.setattr(workers, "current_task", SimpleNamespace(_get_current_object=lambda: sender))
    actor = set_current_permission_actor(None)
    workers.restore_tenant_context(sender=sender)
    try:
        yield business, original, sender
    finally:
        workers.reset_tenant_context(sender=sender)
        reset_current_permission_actor(actor)


def expected(row):
    return {
        "operation_id": "build-1",
        "expected_model_config_revision": row["model_config_revision"],
        "expected_index_generation": row["index_generation"],
    }


@pytest.mark.parametrize("native", [False, True])
async def test_actual_transition_finalizes_resource_and_source_with_same_generation(building, native):
    context, original, _ = building
    if native:

        def finalize():
            with Session(context.sync) as session:
                plan = App.prepare_finalization(session, 40, **expected(original))
                App.apply_finalization(session, plan)
                session.commit()

        await asyncio.to_thread(finalize)
    else:
        async with context.sessions() as session:
            plan = await App.aprepare_finalization(session, 40, **expected(original))
            await App.aapply_finalization(session, plan)
            await session.commit()
    facts = fixtures.state(context)
    row = next(row for row in facts["knowledge"] if row["id"] == 40)
    assert row["model"] == "12" and row["model_transition"] is None and row["state"] == 1
    assert row["model_config_revision"] == 2 and row["index_generation"] == original["index_generation"]
    assert [(ref["slot_key"], ref["target_id"]) for ref in facts["business_resource_reference"]] == [("model", "12")]
    async with context.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await App.aprepare_finalization(session, 40, **expected(original))


@pytest.mark.parametrize("field", ["operation_id", "expected_model_config_revision", "expected_index_generation"])
async def test_obsolete_operation_revision_or_generation_cannot_finalize_a_different_stage(building, field):
    context, original, _ = building
    before = fixtures.state(context)
    arguments = {**expected(original), field: 999 if field == "expected_model_config_revision" else "obsolete"}
    async with context.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await App.aprepare_finalization(session, 40, **arguments)
    assert fixtures.state(context) == before


async def test_reference_failure_keeps_current_pending_models_and_original_stage(building, monkeypatch):
    context, original, _ = building
    before = fixtures.state(context)
    monkeypatch.setattr(
        context.runtime, "aapply_source_bindings", AsyncMock(side_effect=RuntimeError("R2 finalize failed"))
    )
    async with context.sessions() as session:
        plan = await App.aprepare_finalization(session, 40, **expected(original))
        with pytest.raises(RuntimeError, match="R2 finalize failed"):
            await App.aapply_finalization(session, plan)
        await session.rollback()
    assert fixtures.state(context) == before


async def test_expired_real_worker_or_cloned_plan_cannot_apply_finalization(building):
    context, original, sender = building
    before = fixtures.state(context)
    async with context.sessions() as session:
        plan = await App.aprepare_finalization(session, 40, **expected(original))
        with pytest.raises(ResourceReferenceInvalidError):
            await App.aapply_finalization(session, replace(plan))
        workers.reset_tenant_context(sender=sender)
        with pytest.raises(ResourceReferenceInvalidError):
            await App.aapply_finalization(session, plan)
        await session.rollback()
    assert fixtures.state(context) == before


@pytest.mark.parametrize("stage", ["deleted", "deleting"])
async def test_pending_model_must_still_be_eligible_before_publishing_business_binding(building, stage):
    context, original, _ = building
    async with context.sessions() as session, session.begin():
        if stage == "deleted":
            await session.execute(sa.delete(LLMModel).where(LLMModel.id == 12, LLMModel.tenant_id == 101))
        session.add(
            ResourceReferenceTombstone(
                tenant_id=101,
                target_type="model",
                target_id="12",
                target_tenant_id=101,
                operation_id="delete12",
                operation_type="force_delete",
                stage=stage,
                actor_type="user",
                actor_id="7",
            )
        )
    before = fixtures.state(context)
    async with context.sessions() as session:
        with pytest.raises(KnowledgeProcessingConflictError if stage == "deleting" else ResourceReferenceInvalidError):
            await App.aprepare_finalization(session, 40, **expected(original))
    assert fixtures.state(context) == before
