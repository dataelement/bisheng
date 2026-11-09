"""§126 native HTTP admission/query on the actual move application."""

import importlib
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeProcessingJobNotFoundError
from test.knowledge_unification import test_move_processing_admission as stages
from test.knowledge_unification import test_move_processing_owner as base
from test.knowledge_unification.test_job_query_dispatch import actual_processing_task as actual_processing_task
from test.knowledge_unification.test_job_repo import job_tenant as job_tenant
from test.knowledge_unification.test_processing_identity import request_context

store, tenant, moving, accepted, application = base.store, base.tenant, base.moving, base.accepted, base.application


def api():
    return importlib.import_module("bisheng.knowledge.api.endpoints.move_processing")


@asynccontextmanager
async def client(app, monkeypatch):
    module = api()
    web = FastAPI()
    web.include_router(module.router, prefix="/api/v1/knowledge/space")
    web.dependency_overrides[UserPayload.get_login_user] = lambda: app.current
    web.dependency_overrides[module.get_move_owner] = lambda: app.owner

    async def write_scope(request, identity):
        assert identity is app.current and request.headers["X-Management-Tenant"] == "101"

    monkeypatch.setattr(module, "_write_scope", write_scope)
    async with AsyncClient(transport=ASGITransport(app=web), base_url="http://native") as http:
        yield http


async def test_http_precheck_confirmation_accepts_real_durable_move(application, monkeypatch):
    app = application
    await stages.reset_to_before(app)
    with request_context(app.actor):
        async with client(app, monkeypatch) as http:
            checked = await http.post(
                "/api/v1/knowledge/space/10/files/move/precheck",
                headers={"X-Management-Tenant": "101"},
                json={"items": [{"id": 50, "type": "folder"}], "target_space_id": 11, "target_folder_id": 51},
            )
            assert checked.status_code == 200
            plan = checked.json()["data"]
            result = await http.post(
                "/api/v1/knowledge/space/10/files/move/confirm",
                headers={"X-Management-Tenant": "101"},
                json={
                    "confirmation_id": plan["confirmation_id"],
                    "plan_digest": plan["plan_digest"],
                    "idempotency_key": "http-native",
                },
            )
    assert result.status_code == 200 and result.json()["data"]["state"] == "accepted"
    async with app.built.sessions() as session:
        job = await session.get(base.Job, result.json()["data"]["job_id"])
        assert job.pending_dispatch and job.kind == "move_index" and job.move_logical_marker is None
        assert (await session.get(base.File, 81)).knowledge_id == 10


async def test_query_requires_real_job_dual_space_and_current_subject(application, monkeypatch):
    app = application
    module = importlib.import_module("bisheng.knowledge.application.move_processing_access")
    access = module.MoveProcessingAccess(app.owner)

    async def visible(identity, **kwargs):
        return {str(value): ("visible",) for value in kwargs["resource_ids"]}

    monkeypatch.setattr(module, "batch_check_business_actions", visible)
    with request_context(app.actor):
        source = await access.aget(10, app.built.job_id, identity=app.current)
        target = await access.aget(11, app.built.job_id, identity=app.current)
        assert source == target and source.total_count == 1
        with pytest.raises(KnowledgeProcessingJobNotFoundError):
            await access.aget(999, app.built.job_id, identity=app.current)


async def test_native_candidate_is_typed_and_bounded_not_audit_user_authority(application):
    app = application
    async with app.owner._session() as session:
        kwargs = {"space_id": 10, "subject_type": "user", "subject_id": 7, "limit": 1}
        assert await app.owner.move_jobs.alist_query_candidates(session, **kwargs) == (app.built.job_id,)
        assert (
            await app.owner.move_jobs.alist_query_candidates(session, **{**kwargs, "subject_type": "service_account"})
            == ()
        )
        assert await app.owner.move_jobs.alist_query_candidates(session, **{**kwargs, "space_id": 999}) == ()
        assert (
            await app.owner.move_jobs.alist_query_candidates(session, **{**kwargs, "after_id": app.built.job_id}) == ()
        )
        with pytest.raises(ValueError):
            await app.owner.move_jobs.alist_query_candidates(session, **{**kwargs, "limit": 201})
