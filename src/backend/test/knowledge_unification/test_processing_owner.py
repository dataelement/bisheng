"""T620: processing reads and prepares through the real model Owner/Core.

Knowledge, model eligibility, full source admission and R2 use real SQLite;
only the existing permission/sharing transport boundaries are doubled.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.knowledge.application import processing_owner as module
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as Models
from bisheng.knowledge.application.processing_owner import KnowledgeProcessingOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.repositories.processing_job_repository import ProcessingConfiguration
from bisheng.llm.domain.models.llm_server import LLMModel
from test.knowledge_unification import test_kn_model_source as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission


@pytest.fixture
def processing(admission, monkeypatch):
    context, runtime, _, _ = admission
    monkeypatch.setattr(module, "get_knowledge_model_read_runtime", AsyncMock(return_value=runtime))
    return context, KnowledgeProcessingOwner()


async def test_read_uses_actual_current_model_and_ignores_job_model_hint(processing):
    context, owner = processing
    async with context.sessions() as session:
        state = await owner.aread_current(session, 40, identity=context.user)
        assert state.model_id == 11 and state.configuration == ProcessingConfiguration(0, "g0")
        assert state.operation_id is None
        job = SimpleNamespace(
            space_id=40,
            expected_model_config_revision=0,
            expected_index_generation="g0",
            parameters={"operation_id": "irrelevant", "embedding_model_id": 33},
        )
        assert (await owner.aread_current(session, 40, identity=context.user, job=job)).model_id == 11


async def test_prepare_same_model_owns_new_operation_and_same_transaction(processing):
    context, owner = processing
    before = fixtures.fixtures.state(context)
    async with context.sessions() as session:
        prepared = await owner.aprepare(session, 40, identity=context.user, parameters={}, operation_id="job-operation")
        assert prepared.model_id == 11 and prepared.operation_id == "job-operation"
        assert prepared.configuration.model_config_revision == 1
        assert prepared.configuration.index_generation != "g0"
        assert prepared.admitted.slot_key == "model_transition.pending_model_id"
        await session.rollback()
    assert fixtures.fixtures.state(context) == before


async def test_pending_actual_model_not_job_hint_is_used_and_whole_source_must_stay_valid(processing):
    context, owner = processing
    async with context.sessions() as session:
        prepared = await owner.aprepare(
            session, 40, identity=context.user, parameters={"embedding_model_id": 12}, operation_id="new-model"
        )
        job = SimpleNamespace(
            space_id=40,
            expected_model_config_revision=prepared.configuration.model_config_revision,
            expected_index_generation=prepared.configuration.index_generation,
            parameters={"operation_id": "new-model", "embedding_model_id": 33},
        )
        assert (await owner.aread_current(session, 40, job=job)).model_id == 12
        await session.commit()
    async with context.sessions() as session, session.begin():
        await session.execute(sa.delete(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101))
    async with context.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await owner.aread_current(session, 40, job=job)


async def test_new_intent_revision_or_generation_rejects_old_job_even_if_model_matches(processing):
    context, owner = processing
    job = SimpleNamespace(
        space_id=40,
        expected_model_config_revision=0,
        expected_index_generation="g0",
        parameters={"operation_id": "old"},
    )
    async with context.sessions() as session:
        change = await Models.aprepare_rebuild(session, 40, 11, login_user=context.user)
        await Models.aapply_model_change(session, change)
        await session.commit()
    async with context.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await owner.aread_current(session, 40, job=job)


async def test_owner_rejects_unowned_space_and_parameter_model_is_never_a_read_fallback(processing):
    context, owner = processing
    async with context.sessions() as session, session.begin():
        await session.execute(
            sa.update(Knowledge).where(Knowledge.id == 40, Knowledge.tenant_id == 101).values(model=None)
        )
    async with context.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await owner.aread_current(session, 20)
        with pytest.raises(ReferenceCoverageNotReadyError):
            await owner.aread_current(session, 40)


async def test_preview_validates_new_target_without_applying_business_or_r2(processing):
    context, owner = processing
    before = fixtures.fixtures.state(context)
    async with context.sessions() as session:
        preview = await owner.apreview(session, 40, identity=context.user, parameters={"embedding_model_id": 12})
        assert preview.expected_revision == 0 and preview.expected_generation == "g0"
        assert preview.transition["pending_model_id"] == "12"
        await session.commit()
    assert fixtures.fixtures.state(context) == before


async def test_preview_allows_new_valid_target_to_repair_revoked_old_shared_model(processing):
    context, owner = processing
    async with context.sessions() as session:
        # Recreate a separate actual source so this scenario has no in-flight
        # rebuild. No source/R2 mutation is bypassed for the tested request.
        await Models.acreate(
            session,
            Knowledge(id=41, tenant_id=101, user_id=7, name="shared", type=3, model="22", index_generation="g0"),
            login_user=context.user,
            project_created=AsyncMock(),
        )
        await session.commit()
    context.sharing.allowed = frozenset()
    before = fixtures.fixtures.state(context)
    async with context.sessions() as session:
        preview = await owner.apreview(session, 41, identity=context.user, parameters={"embedding_model_id": 12})
        assert preview.model == "12" and preview.transition["current_model_id"] == "12"
        await session.commit()
    assert fixtures.fixtures.state(context) == before
