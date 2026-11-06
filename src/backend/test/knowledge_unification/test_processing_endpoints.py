"""T618: actual ASGI -> processing Service/Owner -> SQL and native worker.

Only login/scope/FGA transports and provider/broker transports are isolated.
The endpoint's production factories and application services remain real.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from sqlmodel import select
from starlette.responses import JSONResponse

from bisheng.admin.application.tenant_scope import EffectiveManagementScope
from bisheng.api.v1.schemas import FileProcessBase
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.admin_scope import AdminScopeChangedError, AdminScopeTenantRequiredError
from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError, KnowledgeProcessingObsoleteError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.api.endpoints import processing as api
from bisheng.knowledge.api.router import knowledge_space_router
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.worker.knowledge import processing_jobs as worker
from test.knowledge_unification import test_processing_dispatch as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application
dispatch = fixtures.dispatch

BASE = "/api/v1/knowledge/space/40"
HEADERS = {"X-Management-Tenant": "101"}


def mount(context, monkeypatch):
    app = FastAPI()
    app.include_router(knowledge_space_router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: context.user
    monkeypatch.setattr(api, "get_async_db_session", context.sessions)
    auth = AsyncMock()
    scope = AsyncMock(return_value=EffectiveManagementScope(101, "own", None))
    monkeypatch.setattr(api, "require_business_action", auth)
    monkeypatch.setattr(api, "resolve_management_scope", scope)

    @app.exception_handler(BaseErrorCode)
    async def business_error(request, error):
        return JSONResponse(error.return_resp_instance().model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse({"status_code": 422, "status_message": "invalid request", "data": None})

    return SimpleNamespace(app=app, auth=auth, scope=scope)


@pytest.fixture
def http(application, monkeypatch):
    return mount(application.context, monkeypatch)


async def call(http, method, path, *, payload=None, headers=None):
    async with AsyncClient(transport=ASGITransport(app=http.app), base_url="http://offline") as client:
        return (await client.request(method, BASE + path, json=payload, headers=headers)).json()


async def accept(http):
    plan = await call(
        http,
        "POST",
        "/processing-jobs/precheck",
        payload={"kind": "embedding_rebuild", "parameters": {}},
        headers=HEADERS,
    )
    assert plan["status_code"] == 200 and plan["data"]["can_execute"]
    payload = {
        "idempotency_key": "http-create",
        "confirmation_id": plan["data"]["confirmation_id"],
        "plan_digest": plan["data"]["plan_digest"],
    }
    accepted = await call(http, "POST", "/processing-jobs", payload=payload, headers=HEADERS)
    assert accepted["status_code"] == 200
    return accepted["data"], payload


async def test_http_acceptance_query_and_hidden_item_paging_use_actual_application(http, application):
    accepted, payload = await accept(http)
    assert accepted["state"] == "accepted" and not accepted["reused"]
    replay = await call(http, "POST", "/processing-jobs", payload=payload, headers=HEADERS)
    assert replay["data"]["job_id"] == accepted["job_id"] and replay["data"]["reused"]
    page = await call(http, "GET", "/processing-jobs?page=1&page_size=1")
    assert page["status_code"] == 200 and page["data"]["total"] == 1
    detail = await call(http, "GET", f"/processing-jobs/{accepted['job_id']}")
    assert detail["data"]["hidden_item_count"] == 1 and detail["data"]["total_count"] == 2
    items = await call(http, "GET", f"/processing-jobs/{accepted['job_id']}/items?page_size=1")
    assert items["data"]["total"] == 1 and items["data"]["data"][0]["file_id"] == 81
    assert "hidden secret" not in str((page, detail, items))
    async with application.context.sessions() as session:
        assert len((await session.exec(select(KnowledgeProcessingJob))).all()) == 1
        assert (await session.exec(select(KnowledgeOperationPlan))).one().operation_id is not None


@pytest.mark.parametrize(
    "headers,code",
    [(None, AdminScopeTenantRequiredError.Code), ({"X-Management-Tenant": "102"}, AdminScopeChangedError.Code)],
)
async def test_http_write_scope_rejection_precedes_plan_or_job(http, application, headers, code):
    result = await call(
        http,
        "POST",
        "/processing-jobs/precheck",
        payload={"kind": "embedding_rebuild", "parameters": {}},
        headers=headers,
    )
    assert result["status_code"] == code
    async with application.context.sessions() as session:
        assert not (await session.exec(select(KnowledgeOperationPlan))).all()
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()


async def test_settings_use_real_legacy_defaults_cas_and_original_container_edit(http, application):
    old = FileProcessBase(knowledge_id=40)
    read = await call(http, "GET", "/processing-settings")
    assert read["status_code"] == 200 and read["data"]["saved_defaults"] is None
    effective = read["data"]["effective_defaults"]
    assert effective["document"]["separator"] == old.separator
    assert effective["document"]["force_ocr"] == old.force_ocr
    assert effective["table"] == old.excel_rule.model_dump(mode="json")
    effective["document"]["chunk_size"] = 512
    payload = {"expected_config_version": 0, "defaults": effective}
    saved = await call(http, "PUT", "/processing-settings", payload=payload, headers=HEADERS)
    assert saved["data"]["config_version"] == 1
    assert (await call(http, "PUT", "/processing-settings", payload=payload, headers=HEADERS))["status_code"] != 200
    assert all(
        item.kwargs["action"] == "edit" and item.kwargs["resource_type"] == "knowledge_space"
        for item in http.auth.await_args_list
    )
    async with application.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        assert root.model_config_revision == 0 and root.index_generation == "g0"
        assert (await session.get(KnowledgeFile, 81)).split_rule == '{"original":"kept"}'
    http.auth.side_effect = PermissionDeniedError()
    assert (await call(http, "GET", "/processing-settings"))["status_code"] == PermissionDeniedError.Code


async def test_http_retry_and_worker_share_actual_durable_state_and_original_failed_scope(dispatch, monkeypatch):
    http = mount(dispatch.app.context, monkeypatch)
    dispatch.vector.add_texts.side_effect = lambda *, texts, metadatas: (
        (_ for _ in ()).throw(RuntimeError("provider")) if metadatas[0]["document_id"] == 82 else None
    )
    assert (await worker._execute_processing_job(dispatch.job_id, dispatch.revision))["state"] == "partial_failed"
    detail = await call(http, "GET", f"/processing-jobs/{dispatch.job_id}")
    assert detail["data"]["retryable"] and detail["data"]["failed_count"] == 1
    retried = await call(
        http,
        "POST",
        f"/processing-jobs/{dispatch.job_id}/retry",
        payload={"idempotency_key": "http-retry", "expected_job_revision": detail["data"]["revision"]},
        headers=HEADERS,
    )
    assert retried["status_code"] == 200 and retried["data"]["accepted"]
    before = await call(http, "GET", f"/processing-jobs/{dispatch.job_id}")
    dispatch.vector.add_texts.side_effect = None
    assert (await worker._execute_processing_job(dispatch.job_id, before["data"]["revision"]))["state"] == "succeeded"
    finished = await call(http, "GET", f"/processing-jobs/{dispatch.job_id}")
    assert finished["data"]["succeeded_count"] == 2 and not finished["data"]["retryable"]
    assert dispatch.vector.add_texts.call_count == 3
    dispatch.vector.col.drop.assert_called_once()


async def test_obsolete_retry_commits_before_http_business_error(http, application):
    accepted, _ = await accept(http)
    async with application.context.sessions() as session:
        job = await application.owner.jobs.aget(session, accepted["job_id"])
        job.expected_model_config_revision = 0
        job.state = "failed"
        revision = job.revision
        await session.commit()
    result = await call(
        http,
        "POST",
        f"/processing-jobs/{accepted['job_id']}/retry",
        payload={"idempotency_key": "obsolete-http", "expected_job_revision": revision},
        headers=HEADERS,
    )
    assert result["status_code"] == KnowledgeProcessingObsoleteError.Code
    async with application.context.sessions() as session:
        assert (await application.owner.jobs.aget(session, accepted["job_id"])).state == "obsolete"


async def test_unassembled_kind_and_bad_pagination_remain_explicit_errors(http):
    result = await call(
        http,
        "POST",
        "/processing-jobs/precheck",
        payload={
            "kind": "metadata_schema_change",
            "parameters": {
                "expected_schema_revision": 0,
                "changes": [{"operation": "add", "field_name": "extra", "field_type": "string"}],
            },
        },
        headers=HEADERS,
    )
    assert result["status_code"] == KnowledgeProcessingConflictError.Code
    assert (await call(http, "GET", "/processing-jobs?page_size=201"))["status_code"] == 422
    assert (await call(http, "GET", "/processing-jobs?state=made_up"))["status_code"] == 422
