from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from bisheng.channel.api.dependencies import get_channel_creation_application_service
from bisheng.channel.api.endpoints.channel_manager import router
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.channel import ChannelPermissionDeniedError

CHANNEL_ID = "channel-string-id"


class _User:
    user_id = 7
    user_name = "operator"
    tenant_id = 1

    def is_admin(self) -> bool:
        return False


def _payload(*, grant: dict | None = None) -> dict:
    data = {
        "name": "资讯频道",
        "source_list": [],
        "visibility": "public",
        "description": "统一权限入口",
        "is_released": True,
    }
    if grant is not None:
        data["initial_permissions"] = {"grants": [grant]}
    return data


def _grant(
    *,
    subject_type: str = "user",
    subject_id: int = 11,
    relation: str = "editor",
) -> dict:
    return {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "relation": relation,
        "include_children": False,
        "model_id": relation,
    }


@pytest.fixture
def app_with_creation_service():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/channel")
    service = SimpleNamespace(create=AsyncMock())

    async def get_user():
        return _User()

    async def get_creation_service():
        return service

    async def handle_error(_request, exc: BaseErrorCode):
        return JSONResponse(status_code=200, content=exc.to_dict())

    app.dependency_overrides[UserPayload.get_login_user] = get_user
    app.dependency_overrides[get_channel_creation_application_service] = get_creation_service
    app.add_exception_handler(BaseErrorCode, handle_error)
    return app, service


def test_create_channel_old_request_compatible(app_with_creation_service):
    app, service = app_with_creation_service
    service.create.return_value = {"id": CHANNEL_ID, "name": "资讯频道"}

    with TestClient(app) as client:
        response = client.post("/api/v1/channel/manager/create", json=_payload())

    body = response.json()
    assert body["status_code"] == 200
    assert body["data"] == {"id": CHANNEL_ID, "name": "资讯频道"}
    assert service.create.await_count == 1
    request_model, login_user, http_request = service.create.await_args.args
    assert request_model.initial_permissions is None
    assert login_user.user_id == _User.user_id
    assert http_request.url.path == "/api/v1/channel/manager/create"


def test_create_channel_with_initial_permissions_success(app_with_creation_service):
    app, service = app_with_creation_service
    service.create.return_value = {
        "id": CHANNEL_ID,
        "name": "资讯频道",
        "initial_permission_result": {"status": "success", "error_code": None},
    }

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/channel/manager/create",
            json=_payload(grant=_grant()),
        )

    body = response.json()
    assert body["status_code"] == 200
    assert body["data"]["id"] == CHANNEL_ID
    assert isinstance(body["data"]["id"], str)
    assert body["data"]["initial_permission_result"] == {
        "status": "success",
        "error_code": None,
    }
    request_model = service.create.await_args.args[0]
    assert request_model.initial_permissions.grants[0].subject_id == 11


def test_create_channel_authorization_failure_keeps_resource_without_retry(
    app_with_creation_service,
):
    app, service = app_with_creation_service
    service.create.return_value = {
        "id": CHANNEL_ID,
        "name": "资讯频道",
        "initial_permission_result": {
            "status": "failed",
            "error_code": ChannelPermissionDeniedError.Code,
        },
    }

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/channel/manager/create",
            json=_payload(grant=_grant()),
        )

    body = response.json()
    assert body["status_code"] == 200
    assert body["data"]["id"] == CHANNEL_ID
    assert body["data"]["initial_permission_result"] == {
        "status": "failed",
        "error_code": ChannelPermissionDeniedError.Code,
    }
    assert service.create.await_count == 1


def test_channel_create_response_item_results(app_with_creation_service):
    app, service = app_with_creation_service
    service.create.return_value = {
        "id": CHANNEL_ID,
        "name": "资讯频道",
        "initial_permission_result": {
            "status": "success",
            "error_code": None,
            "direct_applied_count": 0,
            "invite_created_count": 1,
            "invite_existing_count": 0,
            "failed_count": 0,
            "results": [
                {
                    "operation": "grant",
                    "subject_type": "user",
                    "subject_id": 11,
                    "relation": "viewer",
                    "model_id": "viewer",
                    "outcome": "invite_created",
                    "approval_instance_id": 1201,
                    "error_code": None,
                    "error_message": None,
                }
            ],
        },
    }

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/channel/manager/create",
            json=_payload(grant=_grant()),
        )

    result = response.json()["data"]["initial_permission_result"]
    assert result["invite_created_count"] == 1
    assert result["results"][0]["approval_instance_id"] == 1201


@pytest.mark.parametrize(
    "grant",
    [
        _grant(subject_type="user_group", subject_id=201, relation="owner"),
        _grant(subject_type="user", subject_id=999, relation="viewer"),
    ],
    ids=["invalid-group-owner", "cross-tenant-user"],
)
def test_create_channel_rejects_invalid_initial_subject(
    app_with_creation_service,
    grant: dict,
):
    app, service = app_with_creation_service
    service.create.side_effect = ChannelPermissionDeniedError()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/channel/manager/create",
            json=_payload(grant=grant),
        )

    body = response.json()
    assert body["status_code"] == ChannelPermissionDeniedError.Code
    assert service.create.await_count == 1
