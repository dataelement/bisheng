"""Dedicated Kunlian routes preserve Workflow Owner transport classifications."""

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from bisheng.common.errcode.flow import (
    WorkflowRegistrationConflict,
    WorkflowRegistrationDenied,
    WorkflowRegistrationUnavailable,
)
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.application.kunlian_http import KunlianApiRoute


@pytest.mark.parametrize(
    "error_type", [WorkflowRegistrationConflict, WorkflowRegistrationDenied, WorkflowRegistrationUnavailable]
)
async def test_workflow_owner_errors_keep_real_http_status_and_code(error_type):
    app = FastAPI()
    register_open_api_exception_handlers(app)
    router = APIRouter(route_class=KunlianApiRoute)

    @router.post("/api/v2/kunlian/test-owner")
    async def owner_error():
        raise error_type()

    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v2/kunlian/test-owner")
    owner = error_type()
    assert response.status_code == owner.http_status
    assert response.json()["status_code"] == owner.code
    assert response.json()["status_message"] == owner.message
    assert response.headers["Cache-Control"] == "no-store"
