"""File commands may narrow only against a provably unrelated durable move."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.knowledge.application.knowledge_processing_commands import KnowledgeProcessingCommands
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.repositories.source_move_input_repository import SourceMoveInputRepository
from test.knowledge_unification import test_move_job_reservation as native

store, tenant, moving, accepted = native.store, native.tenant, native.moving, native.accepted


@pytest.mark.parametrize("kind", ["file_resplit", "file_reprocess"])
async def test_unsettled_move_blocks_related_but_not_disjoint_file(moving, accepted, kind):
    prepared = await accepted()
    job = (await native.create(moving, prepared.args)).job
    target = job.scope_manifest[0]
    async with AsyncSession(moving.engine) as session, session.begin():
        await KnowledgeProcessingCommands._require_source_inputs(session, 10, kind, [{"file_id": 98592}])
        with pytest.raises(KnowledgeProcessingConflictError) as exc:
            await KnowledgeProcessingCommands._require_source_inputs(session, 10, kind, [target])
        assert exc.value.kwargs["reason"] == "source_file_move_input_required"
        for op, scope in [("embedding_rebuild", None), ("metadata_schema_change", None), (kind, [target, target])]:
            with pytest.raises(KnowledgeProcessingConflictError) as exc:
                await KnowledgeProcessingCommands._require_source_inputs(session, 10, op, scope)
            assert exc.value.kwargs["reason"] == "source_space_move_input_required"


@pytest.mark.parametrize("kind", ["file_reprocess", "file_resplit"])
async def test_command_precheck_and_confirm_use_independent_frozen_scopes(moving, accepted, monkeypatch, kind):
    from bisheng.knowledge.application import knowledge_processing_commands as commands
    from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest, ProcessingPrecheckRequest

    prepared = await accepted()
    move = (await native.create(moving, prepared.args)).job
    target = {"file_id": 98592, "document_id": 123, "version_id": 456}
    plan = SimpleNamespace(operation=kind, target_manifest=[target], impact={})

    async def locked(session, _ident):
        await session.connection()
        return plan

    plans = SimpleNamespace(_locked=locked, aget_for_execution=AsyncMock(return_value=plan))
    svc = SimpleNamespace(_authorize=AsyncMock(), plans=plans, aprecheck=AsyncMock(), acreate=AsyncMock())
    api = KnowledgeProcessingCommands(service=svc, session_factory=lambda: AsyncSession(moving.engine))
    monkeypatch.setattr(commands, "capture_processing_actor", AsyncMock(return_value=SimpleNamespace(reference={})))
    await api.aprecheck(10, ProcessingPrecheckRequest(kind=kind, targets=[target], parameters={}), identity=None)
    svc.aprecheck.assert_awaited_once()
    confirmation = ProcessingCreateRequest(idempotency_key="k", confirmation_id="c", plan_digest="a" * 64)
    await api.aconfirm(10, confirmation, identity=None)
    svc.acreate.assert_awaited_once()
    plan.target_manifest = move.scope_manifest
    with pytest.raises(KnowledgeProcessingConflictError) as exc:
        await api.aconfirm(10, confirmation, identity=None)
    assert exc.value.kwargs["reason"] == "source_file_move_input_required"
    svc.acreate.assert_awaited_once()


@pytest.mark.parametrize("damage", ["job", "item", "scope", "identity", "manifest"])
async def test_unknown_or_contradictory_move_scope_fails_closed(moving, accepted, damage):
    plan = await accepted()
    job = (await native.create(moving, plan.args)).job
    async with AsyncSession(moving.engine) as session, session.begin():
        if damage == "job":
            await session.execute(sa.delete(Job).where(Job.id == job.id))
        elif damage == "item":
            await session.execute(sa.delete(Item).where(Item.job_id == job.id))
        elif damage == "identity":
            await session.execute(sa.update(Item).where(Item.job_id == job.id).values(file_id=99))
        else:
            values = {"parameters": {}} if damage == "scope" else {"scope_manifest": []}
            await session.execute(sa.update(Job).where(Job.id == job.id).values(**values))
        with pytest.raises(KnowledgeProcessingConflictError) as exc:
            await SourceMoveInputRepository().arequire_released(session, space_id=10, include_copy=False, file_id=98592)
        assert exc.value.kwargs["reason"] == "source_file_move_input_required"
