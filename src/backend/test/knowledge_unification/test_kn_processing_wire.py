"""T097: actual public command boundary delegates the existing processing kernels."""

import pytest
from sqlmodel import select

from bisheng.knowledge.application.knowledge_processing_commands import KnowledgeProcessingCommands
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from test.knowledge_unification import test_empty_model_change as native
from test.knowledge_unification.test_job_service import request

store, tenant, business, admission = native.store, native.tenant, native.business, native.admission
processing, application, empty = native.processing, native.application, native.empty


def confirm(plan):
    return ProcessingCreateRequest(
        confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest, idempotency_key="real-command"
    )


async def test_empty_model_configuration_commits_real_r2_and_replays_without_fake_job(empty):
    app = empty
    commands = KnowledgeProcessingCommands(session_factory=app.context.sessions, service=app.app)
    plan = await commands.aprecheck(40, request(12), identity=app.context.user)
    assert plan.can_execute and plan.impact["configuration_only"] and not plan.impact["retrieval_paused"]
    result = await commands.aconfirm(40, confirm(plan), identity=app.context.user)
    assert result == {"completed": True, "operation": "embedding_rebuild", "space_id": 40, "model_config_revision": 1}
    assert await commands.aconfirm(40, confirm(plan), identity=app.context.user) == result
    async with app.context.sessions() as session:
        row = await session.get(Knowledge, 40)
        assert row.model == "12" and row.model_transition is None and row.model_config_revision == 1
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()


async def test_nonempty_command_returns_real_accepted_job_with_original_items_and_transition(application):
    app = application
    commands = KnowledgeProcessingCommands(session_factory=app.context.sessions, service=app.app)
    plan = await commands.aprecheck(40, request(12), identity=app.context.user)
    assert plan.can_execute and not plan.impact.get("configuration_only")
    result = await commands.aconfirm(40, confirm(plan), identity=app.context.user)
    assert result.accepted and result.state == "accepted"
    async with app.context.sessions() as session:
        job = await session.get(KnowledgeProcessingJob, result.job_id)
        root = await session.get(Knowledge, 40)
        assert job.total_count == 2 and job.pending_dispatch
        assert root.model == "11" and root.model_transition["pending_model_id"] == "12"


async def test_empty_manual_rebuild_is_not_manufactured_into_a_successful_job(empty):
    app = empty
    commands = KnowledgeProcessingCommands(session_factory=app.context.sessions, service=app.app)
    plan = await commands.aprecheck(40, request(), identity=app.context.user)
    assert not plan.can_execute and not plan.impact.get("configuration_only")
