"""Source cleanup cannot discard the index required before the final native ACK."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan as Plan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.repositories.source_move_input_repository import SourceMoveInputRepository
from test.knowledge_unification import test_direct_delete_scope as native

deletion_tenant, db = native.deletion_tenant, native.db


@pytest.mark.parametrize(
    "state,item_state,step,item_tenant,count,logical,allowed",
    [
        ("accepted", "pending", "pending", 101, 1, False, False),
        ("failed", "failed", "move_source_cleaned", 101, 1, True, False),
        ("succeeded", "failed", "move_source_cleaned", 101, 1, True, False),
        ("succeeded", "succeeded", "move_target_verified", 101, 1, True, False),
        ("succeeded", "succeeded", "move_source_cleaned", 202, 1, True, False),
        ("succeeded", "succeeded", "move_source_cleaned", 101, 1, True, True),
        ("accepted", "pending", "pending", 101, 0, False, False),
        ("succeeded", "succeeded", "move_source_cleaned", 101, 0, True, True),
    ],
)
@pytest.mark.parametrize("operation", ["move", "space_copy"])
async def test_actual_persisted_source_plan_job_and_item_ack_are_required(
    db, state, item_state, step, item_tenant, count, logical, allowed, operation
):
    async with db.engine.begin() as connection:
        await connection.run_sync(
            lambda conn: Plan.metadata.create_all(conn, tables=[model.__table__ for model in (Plan, Job, Item)])
        )
    job_id, now = str(uuid4()), datetime(2026, 11, 9)
    async with db.sessions() as session, session.begin():
        session.add(
            Plan(
                tenant_id=101,
                actor_user_id=7,
                actor_reference={},
                operation=operation,
                space_id=1,
                operation_id=job_id,
                consumed_at=now,
                request_hash="a" * 64,
                plan_digest="b" * 64,
                expires_at=now + timedelta(minutes=5),
            )
        )
        session.add(
            Job(
                id=job_id,
                tenant_id=101,
                space_id=2,
                kind="space_copy" if operation == "space_copy" else "move_index",
                state=state,
                actor_user_id=7,
                idempotency_key=job_id,
                request_hash="a" * 64,
                expected_model_config_revision=0,
                total_count=count,
                succeeded_count=count if state == "succeeded" else 0,
                pending_count=0,
                failed_count=0,
                move_logical_marker={"persisted": True} if logical else None,
            )
        )
        if count:
            session.add(
                Item(
                    tenant_id=item_tenant,
                    job_id=job_id,
                    file_id=31,
                    document_id=100,
                    version_id=301,
                    expected_space_id=2,
                    state=item_state,
                    step="copy_completed" if operation == "space_copy" and step == "move_source_cleaned" else step,
                )
            )
    async with db.sessions() as session, session.begin():
        if allowed:
            await SourceMoveInputRepository().arequire_released(session, space_id=1)
        else:
            with pytest.raises(KnowledgeProcessingConflictError):
                await SourceMoveInputRepository().arequire_released(session, space_id=1)
        # Being the destination is not the source-index dependency.
        await SourceMoveInputRepository().arequire_released(session, space_id=2)
