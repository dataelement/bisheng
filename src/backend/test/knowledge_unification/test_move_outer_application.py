"""§129 actual outer classification and same/cross-space confirmation."""

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationConfirmationRequiredError
from bisheng.knowledge.application import move_application as module
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Doc
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.repositories.source_move_input_repository import SourceMoveInputRepository
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileMoveReq
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from test.knowledge_unification import test_move_processing_admission as stages
from test.knowledge_unification import test_move_processing_owner as base
from test.knowledge_unification.test_processing_identity import request_context

store, tenant, moving, accepted, application = base.store, base.tenant, base.moving, base.accepted, base.application


@pytest.fixture
async def outer(application, monkeypatch):
    app = application
    await stages.reset_to_before(app)

    async def actions(identity, *, resource_type, resource_ids, actions):
        return {str(value): frozenset({"move", "visible"}) for value in resource_ids}

    monkeypatch.setattr(module, "batch_check_business_actions", actions)
    return app, module.KnowledgeMoveApplication(owner=app.owner, max_folder_level=9)


def command(plan, key="actual-outer"):
    return ProcessingCreateRequest(
        confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest, idempotency_key=key
    )


async def test_actual_classification_signs_invalid_and_accepts_only_valid_scope(outer):
    app, service = outer
    with request_context(app.actor):
        plan = await service.aprecheck(
            10,
            FileMoveReq(
                items=[{"id": 81, "type": "file"}, {"id": 999, "type": "file"}], target_space_id=11, target_folder_id=51
            ),
            identity=app.current,
        )
        assert plan.can_execute and plan.requires_skip_confirmation
        assert [row.id for row in plan.valid_items] == [81] and plan.invalid_items[0].name is None
        result = await service.aconfirm(10, command(plan), identity=app.current)
    assert result.state == "accepted"
    async with app.built.sessions() as session:
        job = await session.get(Job, result.job_id)
        assert job.total_count == 1 and job.move_logical_marker is None
        assert (await session.get(base.File, 81)).knowledge_id == 10


async def test_same_space_real_p1_then_atomic_document_history_paths_and_replay(outer):
    app, service = outer
    with request_context(app.actor):
        plan = await service.aprecheck(
            10, FileMoveReq(items=[{"id": 81, "type": "file"}], target_space_id=10), identity=app.current
        )
        result = await service.aconfirm(10, command(plan), identity=app.current)
        assert await service.aconfirm(10, command(plan), identity=app.current) == result
    assert result["moved"] == [{"id": 81, "type": "file", "old_parent_id": 50, "cross_space": False}]
    async with app.built.sessions() as session:
        assert (await session.get(base.File, 81)).file_level_path == ""
        assert (await session.get(base.File, 82)).file_level_path == ""
        assert (await session.get(Doc, 80)).file_level_path == ""
        assert (await session.execute(sa.select(sa.func.count()).select_from(Job))).scalar_one() == 0
        # A synchronous same-space P1 is not an asynchronous source-index lease.
        await SourceMoveInputRepository().arequire_released(session, space_id=10)


async def test_legacy_cross_request_cannot_mutate_or_dispatch(outer):
    app, service = outer
    with request_context(app.actor), pytest.raises(KnowledgeOperationConfirmationRequiredError):
        await service.move_legacy(
            10, FileMoveReq(items=[{"id": 81, "type": "file"}], target_space_id=11), identity=app.current
        )


async def test_all_invalid_is_non_executable_review_with_no_fake_scope_or_job(outer):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

    app, service = outer
    with request_context(app.actor):
        plan = await service.aprecheck(
            10, FileMoveReq(items=[{"id": 999, "type": "file"}], target_space_id=11), identity=app.current
        )
        assert not plan.can_execute and not plan.valid_items and plan.invalid_items
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await service.aconfirm(10, command(plan), identity=app.current)
    async with app.built.sessions() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(Job))).scalar_one() == 0


async def test_same_space_sql_failure_keeps_original_p1_and_fresh_plan_resumes(outer, monkeypatch):
    app, service = outer
    with request_context(app.actor):
        plan = await service.aprecheck(
            10, FileMoveReq(items=[{"id": 81, "type": "file"}], target_space_id=10), identity=app.current
        )
        finalize = service.repository.afinalize_same

        async def fail(session, parameters):
            await finalize(session, parameters)
            raise RuntimeError("SQL tail failed after actual updates")

        monkeypatch.setattr(service.repository, "afinalize_same", fail)
        with pytest.raises(RuntimeError):
            await service.aconfirm(10, command(plan), identity=app.current)
        async with app.built.sessions() as session:
            assert (await session.get(base.File, 81)).file_level_path == "/50"
            assert (await session.get(Doc, 80)).file_level_path == "/50"
        fresh = module.KnowledgeMoveApplication(owner=app.owner, max_folder_level=9)
        assert (await fresh.aconfirm(10, command(plan), identity=app.current))["moved"]


@pytest.mark.parametrize("broken", ["primary_path", "orphan_document"])
async def test_same_space_rejects_actual_broken_primary_or_directory_document_chain(outer, broken):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

    app, service = outer
    async with app.built.sessions() as session, session.begin():
        if broken == "primary_path":
            await session.execute(sa.update(base.File.__table__).where(base.File.id == 81).values(file_level_path=""))
        else:
            session.add(Doc(id=90, knowledge_id=10, primary_version_id=999, file_level_path="/50", level=1))
    with request_context(app.actor), pytest.raises(KnowledgeOperationPlanConflictError):
        await service.aprecheck(
            10, FileMoveReq(items=[{"id": 50, "type": "folder"}], target_space_id=10), identity=app.current
        )


@pytest.mark.parametrize("visible", [True, False])
async def test_invalid_processing_names_require_actual_visibility(outer, monkeypatch, visible):
    app, service = outer
    async with app.built.sessions() as session, session.begin():
        await session.execute(sa.update(base.File.__table__).where(base.File.id == 81).values(status=1))
        name = (await session.get(base.File, 81)).file_name

    async def actions(identity, **kwargs):
        return {str(key): ("move", "visible") if visible else ("move",) for key in kwargs["resource_ids"]}

    monkeypatch.setattr(module, "batch_check_business_actions", actions)
    with request_context(app.actor):
        plan = await service.aprecheck(
            10, FileMoveReq(items=[{"id": 81, "type": "file"}], target_space_id=11), identity=app.current
        )
    assert not plan.can_execute and plan.invalid_items[0].reason == "processing"
    assert plan.invalid_items[0].name == (name if visible else None)
