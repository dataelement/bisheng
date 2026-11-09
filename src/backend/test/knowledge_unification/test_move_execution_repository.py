"""Real accepted move facts, bounded execution reads and full-attempt validation."""

import importlib
from copy import deepcopy

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import (
    KnowledgeIdempotencyConflictError,
    KnowledgeOperationPlanChangedError,
    KnowledgeOperationPlanConflictError,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.knowledge.domain.repositories.move_job_ready_repository import MoveJobReadyRepository
from bisheng.knowledge.domain.repositories.move_job_repository import MoveJobRepository
from test.knowledge_unification import test_move_job_ready as ready
from test.knowledge_unification import test_move_job_reservation as reservation

store, tenant, moving = reservation.store, reservation.tenant, reservation.moving
accepted = reservation.accepted


def api():
    return importlib.import_module("bisheng.knowledge.domain.repositories.move_execution_repository")


def execution(built):
    return api().MoveExecutionRepository(move_jobs=built.move, move_ready=built.ready)


@pytest.fixture
async def built(moving, accepted, monkeypatch):
    return await ready.pipeline(moving, accepted, monkeypatch)


async def test_actual_configuration_and_full_attempt_keep_original_scope_and_position(built):
    repo = execution(built)
    async with built.sessions() as session, session.begin():
        config = await repo.aread_configuration(session, job_id=built.job_id)
        assert config.source_space_id == 10 and config.destination_space_id == 20
        assert config.target == ready.CONFIG
        facts = await repo.avalidate_attempt(session, lease=built.lease, jobs=built.repo)
        assert facts.position == "before" and facts.scope == built.confirmed.scope
        assert facts.job_id == built.job_id and facts.plan_id == built.confirmed.args["confirmation_id"]
        logical = await ready.logical(session, built)
        await built.repo.amark_move_ready(session, logical_receipt=logical, lease=built.lease)
    async with built.sessions() as session, session.begin():
        assert (await repo.avalidate_attempt(session, lease=built.lease, jobs=built.repo)).position == "after"


async def test_projection_point_read_has_real_before_then_after_without_plan_payload(built):
    repo = execution(built)
    async with built.sessions() as session, session.begin():
        fact = await repo.aread_projection(session, lease=built.lease, resource_type="folder", resource_id=50)
        assert fact.file["knowledge_id"] == 10 and fact.file["id"] == 50
        assert fact.configuration.destination_space_id == 20
        logical = await ready.logical(session, built)
        await built.repo.amark_move_ready(session, logical_receipt=logical, lease=built.lease)
    async with built.sessions() as session, session.begin():
        assert (await repo.aread_projection(session, lease=built.lease, resource_type="folder", resource_id=50)).file[
            "knowledge_id"
        ] == 20


async def test_item_read_binds_original_snapshot_after_chain_and_primary(built):
    repo = execution(built)
    async with built.sessions() as session, session.begin():
        logical = await ready.logical(session, built)
        await built.repo.amark_move_ready(session, logical_receipt=logical, lease=built.lease)
        item = (await session.execute(sa.select(Item).where(Item.job_id == built.job_id))).scalars().one()
        result = await repo.aread_item(session, job_id=built.job_id, item_id=item.id)
        assert result.leaf.target.file_id == item.file_id
        assert result.file["knowledge_id"] == result.document["knowledge_id"] == 20
        assert result.version["knowledge_file_id"] == item.file_id
        assert result.primary_version["id"] == result.document["primary_version_id"]
        assert result.checkpoint["logical_move"] == item.checkpoint["logical_move"]


@pytest.mark.parametrize("changed", ["snapshot", "target", "job_hash"])
async def test_full_attempt_rejects_changed_actual_acceptance_before_external_io(built, changed):
    repo = execution(built)
    async with built.sessions() as session, session.begin():
        if changed == "job_hash":
            job = await built.repo.aget(session, built.job_id)
            job.request_hash = "a" * 64
        else:
            item = (await session.execute(sa.select(Item).where(Item.job_id == built.job_id))).scalars().one()
            if changed == "snapshot":
                snapshot = deepcopy(item.processing_snapshot)
                snapshot["file_after"]["file_name"] = "tampered"
                item.processing_snapshot = snapshot
            else:
                item.expected_parent_id = 999
    async with built.sessions() as session, session.begin():
        with pytest.raises(
            (KnowledgeOperationPlanConflictError, KnowledgeOperationPlanChangedError, KnowledgeIdempotencyConflictError)
        ):
            await repo.avalidate_attempt(session, lease=built.lease, jobs=built.repo)


async def test_native_prefix_lock_order_and_read_configuration_do_not_expire_public_manifest(built):
    repo = execution(built)
    seen = []
    async with built.sessions() as session, session.begin():
        public = await built.repo.aget(session, built.job_id)
        manifest = public.scope_manifest

        def capture(c, u, sql, p, context, many):
            statement = context.compiled.statement
            if statement.is_select and statement._for_update_arg is not None:
                seen.extend(getattr(table, "name", None) for table in statement.get_final_froms())

        sa.event.listen(session.bind.sync_engine, "before_cursor_execute", capture)
        await repo.aread_configuration(session, job_id=built.job_id)
        assert public.scope_manifest is manifest and "scope_manifest" not in sa.inspect(public).expired_attributes
        await repo._alock_prefix(session, job_id=built.job_id)
        assert seen[:2] == ["knowledge", "knowledge_operation_plan"]


async def test_missing_issuer_and_wrong_ready_binding_are_rejected(built):
    module = api()
    with pytest.raises((TypeError, KnowledgeOperationPlanConflictError)):
        module.MoveExecutionRepository(
            move_jobs=built.move,
            move_ready=MoveJobReadyRepository(move_jobs=MoveJobRepository(cutover=built.cutover)),
        )
    verifier = built.cutover.projection_verifier
    built.cutover.projection_verifier = None
    try:
        with pytest.raises((TypeError, KnowledgeOperationPlanConflictError)):
            execution(built)
    finally:
        built.cutover.projection_verifier = verifier


async def test_item_read_rejects_safety_status_and_changed_version_without_scanning_siblings(built):
    repo = execution(built)
    async with built.sessions() as session, session.begin():
        logical = await ready.logical(session, built)
        await built.repo.amark_move_ready(session, logical_receipt=logical, lease=built.lease)
        item = (await session.execute(sa.select(Item).where(Item.job_id == built.job_id))).scalars().one()
        item_id, file_id = item.id, item.file_id
    async with built.sessions() as session, session.begin():
        await session.execute(sa.update(ready.File).where(ready.File.id == file_id).values(status=7))
    async with built.sessions() as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aread_item(session, job_id=built.job_id, item_id=item_id)


async def test_configuration_reads_actual_source_change_as_facts(built):
    repo = execution(built)
    async with built.sessions() as session, session.begin():
        await session.execute(sa.update(Knowledge).where(Knowledge.id == 10).values(model_config_revision=99))
    async with built.sessions() as session, session.begin():
        assert (await repo.aread_configuration(session, job_id=built.job_id)).source_model_config_revision == 99
