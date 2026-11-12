"""§126 original task proof/entry invokes the real assembled move runner."""

import asyncio
import importlib
from datetime import timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.background_execution import get_current_background_task
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.worker.knowledge import move_worker, processing_jobs
from test.knowledge_unification import test_move_processing_owner as base
from test.knowledge_unification.test_job_query_dispatch import actual_processing_task as actual_processing_task
from test.knowledge_unification.test_job_repo import job_tenant as job_tenant
from test.knowledge_unification.test_move_worker import native as native

store, tenant, moving, accepted, application = base.store, base.tenant, base.moving, base.accepted, base.application


def api():
    return importlib.import_module("bisheng.worker.knowledge.move_jobs")


async def test_untrusted_direct_runner_cannot_start_or_mutate_job(application):
    app = application
    with pytest.raises(ResourceReferenceInvalidError):
        await api().execute_move_job(app.built.job_id, 1, owner=app.owner, proof=None)


async def test_original_task_moves_before_plain_edit_actor_lookup(application, actual_processing_task, monkeypatch):
    app = application
    module = api()
    seen = []

    async def owner():
        return app.owner

    original = module.execute_move_job

    async def execute(*args, **kwargs):
        seen.append(kwargs["proof"])
        return await original(*args, **kwargs)

    monkeypatch.setattr(module, "get_move_owner", owner)
    monkeypatch.setattr(module, "execute_move_job", execute)
    monkeypatch.setattr(processing_jobs, "get_async_db_session", app.owner.sessions)
    async with app.built.sessions() as session:
        revision = (await session.get(base.Job, app.built.job_id)).revision
    result = await processing_jobs._execute_processing_job(app.built.job_id, revision)
    assert result == {"job_id": app.built.job_id, "state": "running"}  # active same lease duplicate is a no-op
    assert seen == [get_current_background_task()]


async def reclaimable(app):
    async with app.built.sessions() as session, session.begin():
        job = await session.get(base.Job, app.built.job_id)
        job.lease_until = app.built.clock[0] - timedelta(seconds=1)
        revision = job.revision
    return revision


def actual_index(app, native, monkeypatch):
    for row in native.source_es.rows:
        if row["_source"]["metadata"]["document_id"] == 81:
            row["_source"]["metadata"]["knowledge_id"] = 10

    async def vector(user_id, *, knowledge, embeddings=None, **kwargs):
        assert not any(session.in_transaction() for session in app.sessions_seen)
        assert user_id == 7
        assert base.processing_identity.get_current_permission_actor().subject_id == 7
        return SimpleNamespace(
            col=native.source_mv if knowledge.id == 10 else native.target_mv,
            embedding_func=native.embedding if embeddings is None else embeddings,
        )

    async def elasticsearch(*, knowledge, **kwargs):
        assert not any(session.in_transaction() for session in app.sessions_seen)
        return native.source_es if knowledge.id == 10 else native.target_es

    monkeypatch.setattr(move_worker.KnowledgeRag, "init_knowledge_milvus_vectorstore", vector)
    monkeypatch.setattr(move_worker.KnowledgeRag, "init_knowledge_es_vectorstore", elasticsearch)


async def test_original_task_real_adapter_checkpoint_ack_and_duplicate_delivery(
    application, actual_processing_task, native, monkeypatch
):
    app = application
    actual_index(app, native, monkeypatch)
    revision = await reclaimable(app)

    async def owner():
        return app.owner

    monkeypatch.setattr(api(), "get_move_owner", owner)
    monkeypatch.setattr(processing_jobs, "get_async_db_session", app.owner.sessions)
    queries, phases = [], {}

    def capture(connection, cursor, statement, params, context, many):
        queries.append(statement)

    async with app.built.sessions() as session:
        engine = session.bind.sync_engine
    sa.event.listen(engine, "before_cursor_execute", capture)
    for name in ("aguard_item", "arenew_item", "arenew_attempt", "asave_item_checkpoint", "acomplete_item"):
        original = getattr(app.owner, name)

        async def measure(*args, _original=original, _name=name, **kwargs):
            before = len(queries)
            result = await _original(*args, **kwargs)
            phases.setdefault(_name, []).append(len(queries) - before)
            return result

        monkeypatch.setattr(app.owner, name, measure)
    # Force the real adapter guard's throttled renewal branch without a sleep.
    timer = iter(range(0, 100000, 20))
    monkeypatch.setattr(api(), "monotonic", lambda: next(timer))
    try:
        result = await processing_jobs._execute_processing_job(app.built.job_id, revision)
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)
    print(
        {
            "actual_move_adapter_owner_sql": {
                key: {"calls": len(values), "per_call": sorted(set(values))} for key, values in phases.items()
            }
        }
    )
    assert set(phases["aguard_item"]) == {78}
    assert set(phases["arenew_attempt"]) == {14}
    assert set(phases["arenew_item"]) == {67}
    assert result == {"job_id": app.built.job_id, "state": "succeeded"}
    assert await processing_jobs._execute_processing_job(app.built.job_id, revision) == result
    async with app.built.sessions() as session:
        item = (await session.execute(sa.select(Item).where(Item.job_id == app.built.job_id))).scalars().one()
        job = await session.get(base.Job, app.built.job_id)
        assert item.state == "succeeded" and item.checkpoint["step"] == "move_source_cleaned"
        assert item.checkpoint["logical_move"] and job.succeeded_count == 1 and job.pending_count == 0
    assert not any(row["_source"]["metadata"]["document_id"] == 81 for row in native.source_es.rows)


@pytest.mark.parametrize("fault", ["cancel", "wrong_result", "extra_checkpoint", "revoked"])
async def test_runner_never_turns_bad_checkpoint_result_or_revocation_into_success(
    application, actual_processing_task, monkeypatch, fault
):
    app = application
    revision = await reclaimable(app)
    invoked = []

    async def revoked(reference):
        raise ResourceReferenceInvalidError(reason="actual_credential_revoked")

    async def execute(**kwargs):
        invoked.append(True)
        assert not any(session.in_transaction() for session in app.sessions_seen)
        if fault == "cancel":
            raise asyncio.CancelledError()
        if fault == "extra_checkpoint":
            async with app.built.sessions() as session, session.begin():
                row = (await session.execute(sa.select(Item).where(Item.job_id == app.built.job_id))).scalars().one()
                row.checkpoint = {**row.checkpoint, "unexpected": True}
            await kwargs["checkpoints"].aload()
        return {"file_id": 81}  # a dict can never be acknowledged as a native result

    monkeypatch.setattr(api(), "apply_move_index_item", execute)
    if fault == "revoked":
        monkeypatch.setattr(base.processing_identity, "resolve_web_runtime_identity", revoked)
    if fault == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await api().execute_move_job(
                app.built.job_id, revision, owner=app.owner, proof=get_current_background_task()
            )
    else:
        result = await api().execute_move_job(
            app.built.job_id, revision, owner=app.owner, proof=get_current_background_task()
        )
        assert result["state"] in {"failed", "partial_failed"}
    async with app.built.sessions() as session:
        job = await session.get(base.Job, app.built.job_id)
        assert job.succeeded_count == 0
        assert job.move_logical_marker is None if fault == "revoked" else job.move_logical_marker is not None
    assert bool(invoked) == (fault != "revoked")


async def test_runner_guard_configuration_obsolete_commits_and_never_acknowledges_success(
    application, actual_processing_task, monkeypatch
):
    from bisheng.knowledge.domain.models.knowledge import Knowledge

    app = application
    revision = await reclaimable(app)

    async def drift(**kwargs):
        async with app.built.sessions() as session, session.begin():
            row = await session.get(Knowledge, 11)
            row.model_config_revision += 1
        await kwargs["guard"]()
        raise AssertionError("obsolete guard must stop external continuation")

    monkeypatch.setattr(api(), "apply_move_index_item", drift)
    result = await api().execute_move_job(
        app.built.job_id, revision, owner=app.owner, proof=get_current_background_task()
    )
    assert result["state"] == "obsolete"
    async with app.built.sessions() as session:
        job = await session.get(base.Job, app.built.job_id)
        assert job.state == "obsolete" and not job.pending_dispatch and job.succeeded_count == 0
