"""§126 original task proof/entry invokes the real assembled move runner."""

import importlib

import pytest

from bisheng.core.context.background_execution import get_current_background_task
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.worker.knowledge import processing_jobs
from test.knowledge_unification import test_move_processing_owner as base
from test.knowledge_unification.test_job_query_dispatch import actual_processing_task as actual_processing_task
from test.knowledge_unification.test_job_repo import job_tenant as job_tenant

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
