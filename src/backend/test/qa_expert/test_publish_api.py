# ruff: noqa: RUF002
"""T027：转公开 API。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.qa_expert import QaExpertPublishDurationInvalidError
from bisheng.qa_expert.api import endpoints
from bisheng.qa_expert.api.router import router


def _user():
    return SimpleNamespace(
        user_id=1,
        user_name="asker",
        tenant_id=1,
        is_admin=lambda: False,
        role=None,
        is_global_super=False,
    )


def _app(service):
    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        from fastapi.responses import JSONResponse

        return JSONResponse({"status_code": exc.code, "status_message": exc.message, "data": None})

    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = _user
    app.dependency_overrides[endpoints.get_publish_service] = lambda: service
    return app


def test_create_publish_request_and_approve():
    svc = SimpleNamespace(
        create_publish_request=AsyncMock(return_value={"id": 7, "status": "pending", "duration_days": 3}),
        decide_publish=AsyncMock(return_value={"id": 7, "status": "approved"}),
        get_request=AsyncMock(return_value={"id": 7, "status": "pending"}),
    )
    client = TestClient(_app(svc))
    created = client.post("/api/v1/qa_experts/questions/20/publish-requests", json={"duration_days": 3})
    assert created.json()["status_code"] == 200
    assert created.json()["data"]["duration_days"] == 3
    approved = client.post("/api/v1/qa_experts/publish-requests/7/approve")
    assert approved.json()["data"]["status"] == "approved"


def test_invalid_duration_18310():
    svc = SimpleNamespace(create_publish_request=AsyncMock(side_effect=QaExpertPublishDurationInvalidError()))
    client = TestClient(_app(svc))
    resp = client.post("/api/v1/qa_experts/questions/20/publish-requests", json={"duration_days": 2})
    assert resp.json()["status_code"] == 18310
