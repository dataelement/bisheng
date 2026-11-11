"""Original move/upload admission precedes busy state, with native lock rechecks."""

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeProcessingConflictError
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan as Plan
from bisheng.permission.domain.models import PermissionProjectionOperation as Projection
from test.knowledge_unification import test_move_outer_application as native
from test.knowledge_unification.test_processing_identity import request_context

store, tenant, moving, accepted, application = (
    native.store,
    native.tenant,
    native.moving,
    native.accepted,
    native.application,
)
outer = native.outer


def request(same):
    return native.FileMoveReq(
        items=[{"id": 81, "type": "file"}],
        target_space_id=10 if same else 11,
        target_folder_id=None if same else 51,
    )


def observed_source(monkeypatch):
    original = native.module.batch_check_business_actions
    calls = []

    async def checked(identity, **kwargs):
        calls.append(kwargs)
        return await original(identity, **kwargs)

    monkeypatch.setattr(native.module, "batch_check_business_actions", checked)
    return calls


async def unchanged(app, plan):
    async with app.built.sessions() as session:
        assert (await session.get(Plan, plan.confirmation_id)).operation_id is None
        assert (await session.get(native.base.File, 81)).knowledge_id == 10
        assert (await session.get(native.base.File, 81)).file_level_path == "/50"
        assert (await session.execute(sa.select(sa.func.count()).select_from(native.Job))).scalar_one() == 0
        assert (await session.execute(sa.select(sa.func.count()).select_from(Projection))).scalar_one() == 0
    assert not app.chat


@pytest.mark.parametrize("same", [False, True])
@pytest.mark.parametrize("change", ["copying", "rebuilding", "model_transition", "permission"])
async def test_confirm_rechecks_current_busy_or_permission_before_consumption(outer, monkeypatch, same, change):
    app, service = outer
    source_calls = observed_source(monkeypatch)
    with request_context(app.actor):
        plan = await service.aprecheck(10, request(same), identity=app.current)
        if change == "permission":

            async def denied(identity, *, resource_type, resource_ids, actions):
                return {str(ident): frozenset({"visible"}) for ident in resource_ids}

            monkeypatch.setattr(native.module, "batch_check_business_actions", denied)
        else:
            async with app.built.sessions() as session, session.begin():
                root = await session.get(Knowledge, 10)
                if change == "model_transition":
                    root.model_transition = {"operation_id": "actual-pending"}
                else:
                    root.state = 2 if change == "copying" else 3
        app.calls.clear()
        source_calls.clear()
        mutations = []

        def changed_sql(connection, cursor, sql, params, execution, many):
            if execution.isinsert or execution.isupdate or execution.isdelete:
                mutations.append(sql)

        async with app.built.sessions() as session:
            engine = session.bind.sync_engine
        sa.event.listen(engine, "before_cursor_execute", changed_sql)
        with pytest.raises(
            KnowledgeOperationPlanChangedError if change == "permission" else KnowledgeProcessingConflictError
        ):
            await service.aconfirm(10, native.command(plan), identity=app.current)
        sa.event.remove(engine, "before_cursor_execute", changed_sql)
        assert not mutations  # no Plan consumption, Job/Item, projection or File writes
        if change != "permission":
            assert source_calls == [
                {"resource_type": "knowledge_file", "resource_ids": (81,), "actions": ("move", "visible")}
            ]
            assert (("knowledge_space", 10, "upload_file") if same else ("folder", 51, "upload_file")) in app.calls
    await unchanged(app, plan)


@pytest.mark.parametrize("same", [False, True])
async def test_authorized_precheck_rechecks_busy_under_original_root_lock(outer, monkeypatch, same):
    app, service = outer
    source_calls = observed_source(monkeypatch)
    port = service.repository if same else app.owner.scope
    method = "aread" if same else "aload_scope"
    read = getattr(port, method)

    async def changed(session, **kwargs):
        if kwargs.get("lock") or kwargs.get("for_update"):
            async with app.built.sessions() as writer, writer.begin():
                (await writer.get(Knowledge, 10)).state = 3
        return await read(session, **kwargs)

    monkeypatch.setattr(port, method, changed)
    with request_context(app.actor), pytest.raises(KnowledgeProcessingConflictError):
        await service.aprecheck(10, request(same), identity=app.current)
    assert source_calls == [{"resource_type": "knowledge_file", "resource_ids": (81,), "actions": ("move", "visible")}]
    assert (("knowledge_space", 10, "upload_file") if same else ("folder", 51, "upload_file")) in app.calls
    async with app.built.sessions() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(Plan))).scalar_one() == 0
    assert not app.chat


async def test_same_confirm_rechecks_busy_after_projection_before_any_file_update(outer, monkeypatch):
    app, service = outer
    project = app.owner.projection.aexecute_or_resume

    async def projected(**kwargs):
        result = await project(**kwargs)
        async with app.built.sessions() as session, session.begin():
            (await session.get(Knowledge, 10)).state = 3
        return result

    with request_context(app.actor):
        plan = await service.aprecheck(10, request(True), identity=app.current)
        monkeypatch.setattr(app.owner.projection, "aexecute_or_resume", projected)
        with pytest.raises(KnowledgeProcessingConflictError):
            await service.aconfirm(10, native.command(plan), identity=app.current)
    async with app.built.sessions() as session:
        assert (await session.get(native.base.File, 81)).file_level_path == "/50"
        assert set((await session.execute(sa.select(Projection.status))).scalars()) == {"FINALIZED"}
        assert (await session.execute(sa.select(sa.func.count()).select_from(native.Job))).scalar_one() == 0
    assert not app.chat


async def test_busy_space_does_not_replace_missing_selection_classification(outer):
    app, service = outer
    async with app.built.sessions() as session, session.begin():
        (await session.get(Knowledge, 10)).state = 3
    with request_context(app.actor):
        review = await service.aprecheck(
            10,
            native.FileMoveReq(items=[{"id": 999, "type": "file"}], target_space_id=11),
            identity=app.current,
        )
    assert not review.can_execute and review.valid_items == []
    assert review.invalid_items[0].reason == "not_found" and review.invalid_items[0].name is None
    await unchanged(app, review)
