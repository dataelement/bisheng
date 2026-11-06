"""T622: explicit rebuild differs from a same-model metadata update.

Actual Knowledge/R2/TargetOwner SQL is used; provider and FGA transports are
the existing fixture boundaries. No broker or vector store is contacted.
"""

import asyncio

import pytest
from sqlmodel import Session

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, KnowledgeRebuildingError
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as App
from test.knowledge_unification import test_kn_model_bindings as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business


@pytest.mark.parametrize("native", [False, True])
async def test_explicit_same_model_creates_operation_revision_and_generation(business, native):
    await fixtures.seed(business)

    def native_rebuild():
        with Session(business.sync) as session:
            plan = App.prepare_rebuild(session, 40, 11, login_user=business.user, operation_id="explicit")
            assert plan.changed and plan.operation_id == "explicit"
            App.apply_model_change(session, plan)
            session.commit()

    if native:
        await asyncio.to_thread(native_rebuild)
    else:
        async with business.sessions() as session:
            plan = await App.aprepare_rebuild(session, 40, 11, login_user=business.user, operation_id="explicit")
            assert plan.changed and plan.operation_id == "explicit"
            await App.aapply_model_change(session, plan)
            await session.commit()
    state = fixtures.state(business)
    row = next(row for row in state["knowledge"] if row["id"] == 40)
    assert row["model"] == "11" and row["state"] == 3
    assert row["model_config_revision"] == 1 and row["index_generation"] != "g0"
    assert row["model_transition"] == {
        "schema_version": 1,
        "operation_id": "explicit",
        "current_model_id": "11",
        "pending_model_id": "11",
    }
    assert {(item["slot_key"], item["target_id"]) for item in state["business_resource_reference"]} == {
        ("model", "11"),
        ("model_transition.pending_model_id", "11"),
    }


async def test_normal_same_model_change_remains_metadata_only(business):
    await fixtures.seed(business)
    before = fixtures.state(business)
    async with business.sessions() as session:
        plan = await App.aprepare_model_change(session, 40, 11, login_user=business.user)
        assert not plan.changed and plan.operation_id is None
        await App.aapply_model_change(session, plan)
        await session.commit()
    assert fixtures.state(business) == before


async def test_explicit_rebuild_and_reference_rows_rollback_with_caller(business):
    await fixtures.seed(business)
    before = fixtures.state(business)
    async with business.sessions() as session:
        plan = await App.aprepare_rebuild(session, 40, 11, login_user=business.user)
        await App.aapply_model_change(session, plan)
        await session.rollback()
    assert fixtures.state(business) == before


async def test_explicit_rebuild_refuses_stale_configuration_and_an_active_operation(business):
    await fixtures.seed(business)
    async with business.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await App.aprepare_rebuild(session, 40, 11, login_user=business.user, expected_model_config_revision=9)
        plan = await App.aprepare_rebuild(session, 40, 11, login_user=business.user)
        await App.aapply_model_change(session, plan)
        await session.commit()
    before = fixtures.state(business)
    async with business.sessions() as session:
        with pytest.raises(KnowledgeRebuildingError):
            await App.aprepare_rebuild(session, 40, 11, login_user=business.user)
        await session.rollback()
    assert fixtures.state(business) == before
