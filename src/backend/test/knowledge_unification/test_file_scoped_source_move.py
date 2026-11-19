"""File commands may narrow only against a provably unrelated durable move."""

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
