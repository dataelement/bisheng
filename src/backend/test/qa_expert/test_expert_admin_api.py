# ruff: noqa: RUF002
"""T029：专家写接口鉴权 API。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.qa_expert import QaExpertAdminRequiredError
from bisheng.qa_expert.api import endpoints
from bisheng.qa_expert.api.router import router


def _portal_admin():
    return SimpleNamespace(
        user_id=9,
        user_name="admin",
        tenant_id=1,
        is_admin=lambda: False,
        role="管理员",
        is_global_super=False,
    )


def _staff():
    return SimpleNamespace(
        user_id=2,
        user_name="staff",
        tenant_id=1,
        is_admin=lambda: False,
        role="员工",
        is_global_super=False,
    )


def _app(service, user):
    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        from fastapi.responses import JSONResponse

        return JSONResponse({"status_code": exc.code, "status_message": exc.message, "data": None})

    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    app.dependency_overrides[endpoints.get_expert_service] = lambda: service
    return app


def test_disable_enable_ok_for_portal_admin():
    svc = SimpleNamespace(
        disable_expert=AsyncMock(return_value={"id": 5, "status": 0}),
        enable_expert=AsyncMock(return_value={"id": 5, "status": 1}),
        delete_expert=AsyncMock(return_value=True),
    )
    client = TestClient(_app(svc, _portal_admin()))
    disabled = client.post("/api/v1/qa_experts/experts/5/disable")
    assert disabled.json()["status_code"] == 200
    enabled = client.post("/api/v1/qa_experts/experts/5/enable")
    assert enabled.json()["data"]["status"] == 1
    deleted = client.delete("/api/v1/qa_experts/experts/5")
    assert deleted.json()["status_code"] == 200
    svc.delete_expert.assert_awaited()


def test_staff_disable_returns_18307():
    svc = SimpleNamespace(disable_expert=AsyncMock(side_effect=QaExpertAdminRequiredError()))
    client = TestClient(_app(svc, _staff()))
    resp = client.post("/api/v1/qa_experts/experts/5/disable")
    assert resp.json()["status_code"] == 18307
