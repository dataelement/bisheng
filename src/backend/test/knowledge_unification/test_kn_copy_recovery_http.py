"""Original copy recovery through real HTTP routes and native SQL/projections."""

from unittest.mock import AsyncMock

import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.permission import PermissionDeniedError, PermissionPublishNotReadyError
from bisheng.knowledge.api.endpoints import processing as endpoints
from bisheng.knowledge.application import move_processing_access, space_copy, space_copy_access
from bisheng.knowledge.application.space_copy_access import SpaceCopyAccess
from bisheng.knowledge.application.space_copy_owner import SpaceCopyOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.permission.domain.models import PermissionProjectionOperation
from test.knowledge_unification.test_job_query_dispatch import actual_processing_task as actual_processing_task
from test.knowledge_unification.test_kn_copy import (
    admission as admission,
)
from test.knowledge_unification.test_kn_copy import (
    application as application,
)
from test.knowledge_unification.test_kn_copy import (
    business as business,
)
from test.knowledge_unification.test_kn_copy import (
    command,
)
from test.knowledge_unification.test_kn_copy import (
    copying as copying,
)
from test.knowledge_unification.test_kn_copy import (
    job_tenant as job_tenant,
)
from test.knowledge_unification.test_kn_copy import (
    processing as processing,
)
from test.knowledge_unification.test_kn_copy import (
    store as store,
)
from test.knowledge_unification.test_kn_copy import (
    tenant as tenant,
)


async def test_http_recovers_uninitialized_copy_without_target_permission_or_duplicate_resources(
    copying, monkeypatch, actual_processing_task
):
    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="HTTP recovery", identity=ctx.user)
    with monkeypatch.context() as patch:
        patch.setattr(SpaceCopyOwner, "aensure_logical", AsyncMock())
        accepted = await app.aconfirm(40, command(plan), identity=ctx.user)
    sid, jid = accepted["knowledge"].id, accepted["processing_job"].job_id
    owner = SpaceCopyOwner(app)
    failed = await owner.afail(jid, 0, error_code=25009)
    monkeypatch.setattr(
        space_copy_access, "require_business_action", AsyncMock(side_effect=PermissionPublishNotReadyError())
    )
    monkeypatch.setattr(move_processing_access, "batch_check_business_actions", AsyncMock(return_value={}))
    access = SpaceCopyAccess(owner)
    monkeypatch.setattr(endpoints, "SpaceCopyAccess", lambda: access)
    web = FastAPI()
    web.include_router(endpoints.router, prefix="/api/v1/knowledge/space")
    web.dependency_overrides[UserPayload.get_login_user] = lambda: ctx.user
    web.dependency_overrides[endpoints.get_processing_service] = lambda: None

    @web.exception_handler(BaseErrorCode)
    async def business_error(request, error):
        return JSONResponse(error.return_resp_instance().model_dump(mode="json"))

    async def write_scope(request, identity):
        assert identity is ctx.user and request.headers["X-Management-Tenant"] == "101"

    monkeypatch.setattr(endpoints, "_write_scope", write_scope)
    path = f"/api/v1/knowledge/space/{sid}/processing-jobs"
    async with AsyncClient(transport=ASGITransport(app=web), base_url="http://native") as http:
        page = (await http.get(path, params={"kind": "space_copy"})).json()
        assert page["status_code"] == 200
        assert page["data"]["total"] == 1 and page["data"]["data"][0]["id"] == jid
        detail = (await http.get(f"{path}/{jid}", params={"kind": "space_copy"})).json()
        assert detail["status_code"] == 200
        assert detail["data"]["retryable"] and detail["data"]["error_code"] == 25009
        with monkeypatch.context() as patch:
            patch.setattr(space_copy, "require_business_action", AsyncMock(side_effect=PermissionDeniedError()))
            denied = (await http.get(f"{path}/{jid}", params={"kind": "space_copy"})).json()
            assert denied["status_code"] == PermissionDeniedError.Code
        retry = (
            await http.post(
                f"{path}/{jid}/retry",
                params={"kind": "space_copy"},
                headers={"X-Management-Tenant": "101"},
                json={"idempotency_key": "original-http-retry", "expected_job_revision": failed.revision},
            )
        ).json()
        assert retry["status_code"] == 200
        assert retry["data"]["job_id"] == jid and retry["data"]["state"] == "accepted"
    async with ctx.sessions() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(Job))).scalar_one() == 1
        assert (await session.get(Knowledge, sid)).state == 2
        operations = (await session.execute(sa.select(PermissionProjectionOperation))).scalars().all()
        assert len(operations) == 3 and all(row.status == "FINALIZED" for row in operations)
