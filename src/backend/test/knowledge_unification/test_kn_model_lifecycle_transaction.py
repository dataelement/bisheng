"""Actual Knowledge/children/outgoing references finalize one caller transaction.

覆盖 AC: AC-68, AC-71, AC-79, AC-87, AC-88, AC-89, AC-91, AC-92.
Projection and external cleanup sequencing belongs to the legacy consumers;
this file establishes native SQL/R2 rollback and retained-model clear semantics.
"""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel import Session

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError, ResourceReferenceInvalidError
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as App
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, QAKnowledge
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification import test_kn_model_bindings as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business


@pytest.fixture
async def lifecycle(business):
    for model in (KnowledgeFile, QAKnowledge):
        model.__table__.create(business.sync)
    async with business.sessions() as session:
        row = Knowledge(id=40, tenant_id=101, user_id=7, name="actual QA", type=1, model="11")
        await App.acreate(session, row, login_user=business.user, project_created=AsyncMock())
        session.add_all(
            [
                KnowledgeFile(id=ident, tenant_id=tenant_id, knowledge_id=40, file_name=f"file{ident}")
                for ident, tenant_id in ((1, 101), (2, 202))
            ]
        )
        session.add_all(
            [
                QAKnowledge(id=ident, tenant_id=tenant_id, knowledge_id=40, questions=["q"], answers="a")
                for ident, tenant_id in ((1, 101), (2, 202))
            ]
        )
        await session.commit()
    return business


def state(context):
    result = fixtures.state(context)
    with context.sync.connect() as connection:
        for model in (KnowledgeFile, QAKnowledge):
            result[model.__tablename__] = (
                connection.execute(sa.select(model.__table__).order_by(model.id)).mappings().all()
            )
    return result


@pytest.mark.parametrize("native", [False, True])
async def test_true_delete_resource_children_and_outgoing_refs_share_external_rollback(lifecycle, native):
    context = lifecycle
    before = state(context)
    if native:
        import asyncio

        def remove():
            with Session(context.sync) as session:
                plan = App.prepare_removal(session, 40, login_user=context.user)
                App.apply_removal(session, plan)
                session.rollback()

        await asyncio.to_thread(remove)
    else:
        async with context.sessions() as session:
            plan = await App.aprepare_removal(session, 40, login_user=context.user)
            await App.aapply_removal(session, plan)
            await session.rollback()
    assert state(context) == before


async def test_true_delete_commits_zero_inactive_outgoing_source_and_only_owned_children(lifecycle):
    context = lifecycle
    async with context.sessions() as session:
        plan = await App.aprepare_removal(session, 40, login_user=context.user)
        await App.aapply_removal(session, plan)
        await session.commit()
    after = state(context)
    assert all(row["id"] != 40 for row in after["knowledge"])
    assert not after["business_resource_reference"]
    source = next(row for row in after["business_reference_set"] if row["record_kind"] == "source")
    assert not source["effective"] and source["ready"]
    assert [row["tenant_id"] for row in after["knowledgefile"]] == [202]
    assert [row["tenant_id"] for row in after["qaknowledge"]] == [202]


@pytest.mark.parametrize("stage", ["deleted", "deleting"])
async def test_clear_retains_model_source_even_with_unusable_model_and_does_not_execute_it(lifecycle, stage):
    context = lifecycle
    async with context.sessions() as session, session.begin():
        if stage == "deleted":
            await session.execute(sa.delete(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101))
        session.add(
            ResourceReferenceTombstone(
                tenant_id=101,
                target_type="model",
                target_id="11",
                target_tenant_id=101,
                operation_id="deletion-1",
                operation_type="force_delete",
                stage=stage,
                actor_type="user",
                actor_id="7",
            )
        )
    before = state(context)
    async with context.sessions() as session:
        plan = await App.aprepare_removal(session, 40, login_user=context.user, only_clear=True)
        await App.aapply_removal(session, plan)
        await session.commit()
    after = state(context)
    assert after["knowledge"] == before["knowledge"]
    assert after["business_resource_reference"] == before["business_resource_reference"]
    assert after["business_reference_set"] == before["business_reference_set"]
    assert [row["tenant_id"] for row in after["knowledgefile"]] == [202]
    assert [row["tenant_id"] for row in after["qaknowledge"]] == [202]


async def test_reference_finalize_failure_rolls_back_actual_delete_and_all_children(lifecycle, monkeypatch):
    context = lifecycle
    before = state(context)
    monkeypatch.setattr(context.runtime, "aapply_source_bindings", AsyncMock(side_effect=RuntimeError("R2 failed")))
    async with context.sessions() as session:
        plan = await App.aprepare_removal(session, 40, login_user=context.user)
        with pytest.raises(RuntimeError, match="R2 failed"):
            await App.aapply_removal(session, plan)
        await session.rollback()
    assert state(context) == before


async def test_deleting_target_freezes_actual_source_removal(lifecycle):
    context = lifecycle
    async with context.sessions() as session, session.begin():
        session.add(
            ResourceReferenceTombstone(
                tenant_id=101,
                target_type="model",
                target_id="11",
                target_tenant_id=101,
                operation_id="deletion-1",
                operation_type="force_delete",
                stage="deleting",
                actor_type="user",
                actor_id="7",
            )
        )
    before = state(context)
    async with context.sessions() as session:
        with pytest.raises(KnowledgeProcessingConflictError):
            await App.aprepare_removal(session, 40, login_user=context.user)
    assert state(context) == before


async def test_removal_plan_never_accepts_clone_cross_transaction_or_reflected_clear_flag(lifecycle):
    context = lifecycle
    before = state(context)
    async with context.sessions() as session, context.sessions() as other:
        plan = await App.aprepare_removal(session, 40, login_user=context.user)
        with pytest.raises(ResourceReferenceInvalidError):
            await App.aapply_removal(session, replace(plan))
        with pytest.raises(ResourceReferenceInvalidError):
            await App.aapply_removal(other, plan)
        object.__setattr__(plan, "only_clear", True)
        with pytest.raises(ResourceReferenceInvalidError):
            await App.aapply_removal(session, plan)
    assert state(context) == before
