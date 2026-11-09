"""§126 native HTTP admission/query on the actual move application."""

import importlib
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeProcessingJobNotFoundError
from bisheng.knowledge.api.endpoints import processing
from bisheng.worker.knowledge import processing_jobs
from test.knowledge_unification import test_move_processing_admission as stages
from test.knowledge_unification import test_move_processing_owner as base
from test.knowledge_unification import test_move_task_runner as runner
from test.knowledge_unification.test_job_query_dispatch import actual_processing_task as actual_processing_task
from test.knowledge_unification.test_job_repo import job_tenant as job_tenant
from test.knowledge_unification.test_move_worker import native as native
from test.knowledge_unification.test_processing_identity import request_context

store, tenant, moving, accepted, application = base.store, base.tenant, base.moving, base.accepted, base.application


def api():
    return importlib.import_module("bisheng.knowledge.api.endpoints.move_processing")


@asynccontextmanager
async def client(app, monkeypatch):
    module = api()
    web = FastAPI()
    web.include_router(module.router, prefix="/api/v1/knowledge/space")
    legacy = importlib.import_module("bisheng.knowledge.api.endpoints.knowledge_space")
    web.include_router(legacy.router, prefix="/api/v1")
    web.include_router(processing.router, prefix="/api/v1/knowledge/space")

    @web.exception_handler(BaseErrorCode)
    async def business_error(request, error):
        return JSONResponse(error.return_resp_instance().model_dump(mode="json"))

    async def owner():
        return app.owner

    async def visible(identity, **kwargs):
        return {str(value): ("visible",) for value in kwargs["resource_ids"]}

    access = importlib.import_module("bisheng.knowledge.application.move_processing_access")
    monkeypatch.setattr(access, "batch_check_business_actions", visible)
    monkeypatch.setattr(processing, "get_move_owner", owner)
    web.dependency_overrides[UserPayload.get_login_user] = lambda: app.current
    from bisheng.knowledge.application import move_application
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    service = KnowledgeSpaceService(request=None, login_user=app.current)

    async def move_factory():
        return move_application.KnowledgeMoveApplication(owner=app.owner, max_folder_level=9)

    async def classified(identity, **kwargs):
        return {str(value): ("move", "visible") for value in kwargs["resource_ids"]}

    service.move_application_factory = move_factory
    monkeypatch.setattr(move_application, "batch_check_business_actions", classified)
    web.dependency_overrides[module.get_knowledge_space_service] = lambda: service

    async def write_scope(request, identity):
        assert identity is app.current and request.headers["X-Management-Tenant"] == "101"

    monkeypatch.setattr(module, "_write_scope", write_scope)
    monkeypatch.setattr(processing, "_write_scope", write_scope)
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


async def accept_http(app, http):
    response = await http.post(
        "/api/v1/knowledge/space/10/files/move/precheck",
        headers={"X-Management-Tenant": "101"},
        json={"items": [{"id": 50, "type": "folder"}], "target_space_id": 11, "target_folder_id": 51},
    )
    plan = response.json()["data"]
    accepted = (
        await http.post(
            "/api/v1/knowledge/space/10/files/move/confirm",
            headers={"X-Management-Tenant": "101"},
            json={
                "confirmation_id": plan["confirmation_id"],
                "plan_digest": plan["plan_digest"],
                "idempotency_key": "entire-http-chain",
            },
        )
    ).json()["data"]
    app.built.job_id = accepted["job_id"]
    return accepted


@pytest.mark.parametrize("fail_after_verified", [False, True])
async def test_http_confirmation_actual_worker_query_and_forward_checkpoint_retry(
    application, actual_processing_task, native, monkeypatch, fail_after_verified
):
    app = application
    await stages.reset_to_before(app)
    runner.actual_index(app, native, monkeypatch)

    async def owner():
        return app.owner

    monkeypatch.setattr(runner.api(), "get_move_owner", owner)
    monkeypatch.setattr(processing_jobs, "get_async_db_session", app.owner.sessions)
    save = app.owner.asave_item_checkpoint
    failed = []

    async def save_then_lost_ack(*args, **kwargs):
        ack = await save(*args, **kwargs)
        if fail_after_verified and not failed and kwargs["step"] == "move_target_verified":
            failed.append(True)
            raise RuntimeError("actual checkpoint COMMIT ACK lost")
        return ack

    monkeypatch.setattr(app.owner, "asave_item_checkpoint", save_then_lost_ack)
    with request_context(app.actor):
        async with client(app, monkeypatch) as http:
            accepted = await accept_http(app, http)
            async with app.built.sessions() as session:
                revision = (await session.get(base.Job, accepted["job_id"])).revision
            outcome = await processing_jobs._execute_processing_job(app.built.job_id, revision)
            path = f"/api/v1/knowledge/space/10/processing-jobs/{app.built.job_id}"
            read = (await http.get(path + "?kind=move_index")).json()["data"]
            assert read["state"] == ("failed" if fail_after_verified else "succeeded") == outcome["state"]
            listing = (await http.get("/api/v1/knowledge/space/10/processing-jobs?kind=move_index")).json()["data"]
            assert listing["total"] == 1 and listing["data"][0]["id"] == app.built.job_id
            details = (await http.get(path + "/items?kind=move_index")).json()["data"]
            assert details["total"] == 1 and details["data"][0]["file_id"] == 81
            if fail_after_verified:
                assert read["retryable"] and native.source_es.rows
                app.current.token_version += 1
                app.current._runtime_credential_reference["token_version"] = app.current.token_version
                retried = (
                    await http.post(
                        path + "/retry?kind=move_index",
                        headers={"X-Management-Tenant": "101"},
                        json={"idempotency_key": "after-native-verified", "expected_job_revision": read["revision"]},
                    )
                ).json()["data"]
                assert retried["accepted"] and retried["state"] == "accepted"
                async with app.built.sessions() as session:
                    job = await session.get(base.Job, app.built.job_id)
                    retry_revision = job.revision
                    assert job.actor_reference["credential_reference"]["token_version"] == 3
                assert (await processing_jobs._execute_processing_job(app.built.job_id, retry_revision))[
                    "state"
                ] == "succeeded"
                assert (await http.get(path + "?kind=move_index")).json()["data"]["state"] == "succeeded"
    assert not any(row["_source"]["metadata"]["document_id"] == 81 for row in native.source_es.rows)
    assert app.chat and not any(session.in_transaction() for session in app.sessions_seen)


async def test_zero_index_item_http_still_actual_logical_cutover_and_completed_ready(
    application, actual_processing_task, monkeypatch
):
    import sqlalchemy as sa

    app = application
    await stages.reset_to_before(app)
    async with app.built.sessions() as session, session.begin():
        await session.execute(
            sa.update(base.File.__table__).where(base.File.id == 81, base.File.tenant_id == 101).values(status=3)
        )

    async def owner():
        return app.owner

    async def no_index(**kwargs):
        raise AssertionError("zero Item cannot enter external index IO")

    monkeypatch.setattr(runner.api(), "get_move_owner", owner)
    monkeypatch.setattr(runner.api(), "apply_move_index_item", no_index)
    monkeypatch.setattr(processing_jobs, "get_async_db_session", app.owner.sessions)
    with request_context(app.actor):
        async with client(app, monkeypatch) as http:
            await accept_http(app, http)
            async with app.built.sessions() as session:
                job = await session.get(base.Job, app.built.job_id)
                revision = job.revision
                assert job.total_count == 0 and job.move_logical_marker is None
            assert (await processing_jobs._execute_processing_job(app.built.job_id, revision))["state"] == "succeeded"
            async with app.built.sessions() as session:
                job = await session.get(base.Job, app.built.job_id)
                assert job.move_logical_marker and (await session.get(base.File, 81)).knowledge_id == 11
            read = (
                await http.get(f"/api/v1/knowledge/space/11/processing-jobs/{app.built.job_id}?kind=move_index")
            ).json()["data"]
            assert read["total_count"] == 0 and read["state"] == "succeeded"
    assert app.chat


async def test_existing_beat_recovers_move_broker_failure_and_preserves_real_task_envelope(
    application, actual_processing_task, monkeypatch
):
    from datetime import timedelta
    from unittest.mock import AsyncMock, Mock

    app = application
    await stages.reset_to_before(app)
    with request_context(app.actor):
        async with client(app, monkeypatch) as http:
            await accept_http(app, http)
    publish = Mock(side_effect=RuntimeError("actual broker unavailable"))
    monkeypatch.setattr(processing_jobs, "_new_owner", lambda: app.owner)
    monkeypatch.setattr(processing_jobs, "get_async_db_session", app.owner.sessions)
    monkeypatch.setattr(processing_jobs, "_active_tenant_ids", AsyncMock(return_value=[101]))
    monkeypatch.setattr(processing_jobs.execute_processing_job, "apply_async", publish)
    assert await processing_jobs._dispatch_pending_processing_jobs() == 0
    async with app.built.sessions() as session:
        job = await session.get(base.Job, app.built.job_id)
        assert job.pending_dispatch and job.dispatch_attempts == 1
    app.built.clock[0] += timedelta(minutes=2)
    publish.side_effect = None
    assert await processing_jobs._dispatch_pending_processing_jobs() == 1
    envelope = publish.call_args.kwargs
    assert envelope["queue"] == "knowledge_celery" and envelope["headers"] == {"tenant_id": 101}
    assert envelope["kwargs"] == {"job_id": app.built.job_id, "expected_dispatch_revision": job.revision}
    async with app.built.sessions() as session:
        job = await session.get(base.Job, app.built.job_id)
        assert job.pending_dispatch and job.dispatch_attempts == 2


async def test_current_upload_denial_hides_candidate_and_invisible_details_are_trimmed(application, monkeypatch):
    from bisheng.common.errcode.permission import PermissionDeniedError
    from bisheng.knowledge.application import move_processing_admission as admission

    app = application
    module = importlib.import_module("bisheng.knowledge.application.move_processing_access")
    access = module.MoveProcessingAccess(app.owner)

    async def hidden(identity, **kwargs):
        return {}

    monkeypatch.setattr(module, "batch_check_business_actions", hidden)
    with request_context(app.actor):
        detail = await access.aget(10, app.built.job_id, identity=app.current)
        assert detail.hidden_item_count == 1
        items = await access.alist_items(10, app.built.job_id, identity=app.current)
        assert items.total == 0 and items.data == []

        async def deny(identity, **kwargs):
            raise PermissionDeniedError(reason="actual_destination_upload_revoked")

        monkeypatch.setattr(admission, "require_business_action", deny)
        result = await access.alist(10, identity=app.current)
        assert result.total == 0 and result.data == []
        with pytest.raises(PermissionDeniedError):
            await access.aget(10, app.built.job_id, identity=app.current)


async def test_factory_uses_actual_registered_reference_runtime_without_permission_fallback(application, monkeypatch):
    from bisheng.permission.application import process_runtime
    from bisheng.resource_reference.application import access as references

    app = application
    module = importlib.import_module("bisheng.knowledge.application.move_processing_access")
    original = references._runtime
    references.configure_reference_binding_runtime(app.owner.reference_runtime)

    async def components():
        return app.built.bridge.components

    monkeypatch.setattr(module, "get_async_db_session", app.owner.sessions)
    monkeypatch.setattr(process_runtime, "get_f048_process_runtime", components)
    try:
        actual = await module.get_move_owner()
        assert actual.reference_runtime is app.owner.reference_runtime
        assert await actual.projection._composition() is app.built.bridge.components
        assert actual.cutover.projection_verifier is actual.projection
    finally:
        references.configure_reference_binding_runtime(original)


async def test_candidate_sql_is_scalar_and_explicit_tenant_under_foreign_or_bypass_context(application):
    import sqlalchemy as sa

    from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id

    app = application
    captured = []

    def capture(connection, cursor, statement, params, context, many):
        captured.append((statement, params))

    async with app.owner._session() as session:
        engine = session.bind.sync_engine
        sa.event.listen(engine, "before_cursor_execute", capture)
        try:
            arguments = {"space_id": 10, "subject_type": "user", "subject_id": 7}
            assert await app.owner.move_jobs.alist_query_candidates(session, **arguments) == (app.built.job_id,)
            sql, binds = captured[-1]
            assert "knowledge_processing_job.tenant_id = ?" in sql and 101 in binds
            assert "knowledge_operation_plan.tenant_id = ?" in sql
            assert "knowledge_processing_retry_receipt.tenant_id = ?" in sql
            assert "scope_manifest" not in sql and "parameters" not in sql and "actor_reference" not in sql
            token = current_tenant_id.set(202)
            try:
                assert await app.owner.move_jobs.alist_query_candidates(session, **arguments) == ()
            finally:
                current_tenant_id.reset(token)
            with bypass_tenant_filter():
                with pytest.raises(ValueError):
                    await app.owner.move_jobs.alist_query_candidates(session, **arguments)
        finally:
            sa.event.remove(engine, "before_cursor_execute", capture)


async def test_default_ordinary_http_list_is_not_poisoned_or_counted_by_move_rows(application, monkeypatch):
    from bisheng.knowledge.domain.services import processing_job_service as service_module

    app = application

    async def permitted(*args, **kwargs):
        return None

    async def visible(identity, **kwargs):
        return {str(value): ("visible",) for value in kwargs["resource_ids"]}

    monkeypatch.setattr(service_module, "require_business_action", permitted)
    monkeypatch.setattr(service_module, "batch_check_business_actions", visible)
    monkeypatch.setattr(processing, "get_async_db_session", app.owner.sessions)
    with request_context(app.actor):
        async with client(app, monkeypatch) as http:
            response = await http.get("/api/v1/knowledge/space/11/processing-jobs")
    result = response.json()
    assert result["status_code"] == 200
    assert result["data"] == {"data": [], "total": 0}


async def test_legacy_same_space_http_is_synchronous_and_cross_bare_is_rejected(application, monkeypatch):
    app = application
    await stages.reset_to_before(app)
    with request_context(app.actor):
        async with client(app, monkeypatch) as http:
            path = "/api/v1/knowledge/space/10/files/move"
            request = {"items": [{"id": 81, "type": "file"}], "target_space_id": 11}
            denied = (await http.post(path, json=request)).json()
            assert denied["status_code"] != 200
            request["target_space_id"] = 10
            result = (await http.post(path, json=request)).json()
    assert result["status_code"] == 200 and result["data"]["moved"][0]["id"] == 81
    assert "accepted" not in result["data"]
    async with app.built.sessions() as session:
        assert (await session.get(base.File, 81)).file_level_path == ""
        assert (await session.get(base.File, 82)).file_level_path == ""
