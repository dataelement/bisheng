"""ASGI deletion plans run the actual application and SQL scope collection.

Authentication/scope/FGA transports use the existing native fixture boundaries;
this suite does not claim deployed browser or real middleware coverage.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.knowledge.api.endpoints import deletion as api
from bisheng.knowledge.application.knowledge_deletion import get_deletion_application
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from test.e2e.helpers.api import assert_resp_200, assert_resp_error
from test.knowledge_unification import test_kn_delete_plan as native

deletion_tenant, db, context, service, application = (
    native.deletion_tenant,
    native.db,
    native.context,
    native.service,
    native.application,
)


@pytest.fixture
async def http(application, monkeypatch):
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1/knowledge/space")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: application.user
    app.dependency_overrides[get_deletion_application] = lambda: application
    monkeypatch.setattr(api, "_write_scope", AsyncMock())

    @app.exception_handler(BaseErrorCode)
    async def error(request, exception):
        return JSONResponse(exception.return_resp_instance().model_dump(mode="json"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://offline") as client:
        yield client


@pytest.mark.parametrize("status", [1, 5])
async def test_ac01_waiting_or_processing_file_delete_plan_is_executable(http, application, context, status):
    """AC-01: ordinary pending parse status never blocks deletion consent."""
    async with context.db.sessions() as session, session.begin():
        (await session.get(KnowledgeFile, 40)).status = status
    result = assert_resp_200(
        await http.post("/api/v1/knowledge/space/1/files/delete/precheck", json={"items": [{"type": "file", "id": 40}]})
    )
    assert result["can_execute"] and not result["invalid_items"]


async def test_ac02_rebuilding_space_can_delete_but_copy_cannot(http, context):
    """AC-02: whole-space delete supersedes rebuild and preserves copy protection."""
    async with context.db.sessions() as session, session.begin():
        (await session.get(Knowledge, 2)).state = 3
    assert assert_resp_200(await http.post("/api/v1/knowledge/space/2/delete/precheck", json={}))["can_execute"]
    async with context.db.sessions() as session, session.begin():
        (await session.get(Knowledge, 2)).state = 2
    assert_resp_error(
        await http.post("/api/v1/knowledge/space/2/delete/precheck", json={}), KnowledgeProcessingConflictError.Code
    )


async def test_ac03_delete_denial_keeps_names_and_dependency_facts_private(http, application, monkeypatch):
    """AC-03: removing status protection must preserve actual delete authorization."""

    async def denied(identity, *, resource_type, resource_ids, actions):
        return {str(ident): frozenset() for ident in resource_ids}

    monkeypatch.setattr(native.module.admission, "batch_check_business_actions", denied)
    inspection = AsyncMock(side_effect=AssertionError("denied rows must not read dependencies"))
    monkeypatch.setattr(application.references, "ainspect", inspection)
    result = assert_resp_200(
        await http.post("/api/v1/knowledge/space/1/files/delete/precheck", json={"items": [{"type": "file", "id": 40}]})
    )
    assert not result["can_execute"] and not result["valid_items"]
    assert result["invalid_items"][0]["reason"] == "no_permission"
    assert result["invalid_items"][0].get("name") is None
    inspection.assert_not_awaited()
