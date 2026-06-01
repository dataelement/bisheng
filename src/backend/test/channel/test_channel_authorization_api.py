from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from bisheng.channel.api.endpoints.channel_manager import router
from bisheng.channel.domain.schemas.channel_authorization_schema import (
    ChannelAuthorizeResponse,
    ChannelPermissionEntry,
    ChannelRelationModelItem,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.channel import ChannelPermissionDeniedError


class _User:
    user_id = 7
    user_name = 'operator'
    tenant_id = 1
    user_role = [2]

    def is_admin(self):
        return False


class _AuthService:
    def __init__(self):
        self.list_permissions = AsyncMock(return_value=[
            ChannelPermissionEntry(
                subject_type='user',
                subject_id=11,
                subject_name='Alice',
                relation='viewer',
                model_id='viewer',
                model_name='可查看',
            )
        ])
        self.authorize_channel = AsyncMock(return_value=ChannelAuthorizeResponse(
            synced_user_count=0,
            affected_member_count=0,
        ))
        self.grantable_relation_models = AsyncMock(return_value=[
            ChannelRelationModelItem(
                id='viewer',
                name='可查看',
                relation='viewer',
                grant_tier='usage',
                permissions=['view_channel'],
                permissions_explicit=False,
                is_system=True,
            )
        ])
        self.list_grant_users = AsyncMock(return_value=[{'user_id': 11, 'user_name': 'Alice'}])
        self.list_grant_departments = AsyncMock(return_value=[{'id': 100, 'name': '研发部'}])
        self.list_grant_user_groups = AsyncMock(return_value=[{'id': 200, 'name': '项目组'}])


@pytest.fixture
def app_with_auth_service():
    from bisheng.channel.api.dependencies import get_channel_authorization_service

    app = FastAPI()
    app.include_router(router, prefix='/api/v1/channel')
    service = _AuthService()

    async def get_user():
        return _User()

    async def get_auth_service():
        return service

    async def handle_error(_request, exc: BaseErrorCode):
        return JSONResponse(status_code=200, content=exc.to_dict())

    app.dependency_overrides[UserPayload.get_login_user] = get_user
    app.dependency_overrides[get_channel_authorization_service] = get_auth_service
    app.add_exception_handler(BaseErrorCode, handle_error)
    return app, service


def test_get_channel_permissions_endpoint(app_with_auth_service):
    app, service = app_with_auth_service
    with TestClient(app) as client:
        response = client.get('/api/v1/channel/manager/channel-1/permissions')

    body = response.json()
    assert body['status_code'] == 200
    assert body['data'][0]['subject_id'] == 11
    service.list_permissions.assert_awaited_once()


def test_authorize_channel_endpoint(app_with_auth_service):
    app, service = app_with_auth_service
    with TestClient(app) as client:
        response = client.post(
            '/api/v1/channel/manager/channel-1/authorize',
            json={
                'grants': [{'subject_type': 'user', 'subject_id': 11, 'relation': 'viewer'}],
                'revokes': [],
            },
        )

    body = response.json()
    assert body['status_code'] == 200
    assert body['data']['synced_user_count'] == 0
    service.authorize_channel.assert_awaited_once()


def test_get_grantable_relation_models_endpoint(app_with_auth_service):
    app, service = app_with_auth_service
    with TestClient(app) as client:
        response = client.get('/api/v1/channel/manager/channel-1/grantable-relation-models')

    body = response.json()
    assert body['status_code'] == 200
    assert body['data'][0]['id'] == 'viewer'
    service.grantable_relation_models.assert_awaited_once()


@pytest.mark.parametrize(
    ('path', 'method_name'),
    [
        ('/api/v1/channel/manager/channel-1/grant-subjects/users?keyword=a&page=1&page_size=20', 'list_grant_users'),
        ('/api/v1/channel/manager/channel-1/grant-subjects/departments', 'list_grant_departments'),
        ('/api/v1/channel/manager/channel-1/grant-subjects/user-groups?keyword=g', 'list_grant_user_groups'),
    ],
)
def test_get_channel_grant_subject_endpoints(app_with_auth_service, path: str, method_name: str):
    app, service = app_with_auth_service
    with TestClient(app) as client:
        response = client.get(path)

    body = response.json()
    assert body['status_code'] == 200
    assert isinstance(body['data'], list)
    getattr(service, method_name).assert_awaited_once()


def test_channel_permission_denied_returns_error_envelope(app_with_auth_service):
    app, service = app_with_auth_service
    service.authorize_channel.side_effect = ChannelPermissionDeniedError()

    with TestClient(app) as client:
        response = client.post(
            '/api/v1/channel/manager/channel-1/authorize',
            json={
                'grants': [{'subject_type': 'user', 'subject_id': 11, 'relation': 'viewer'}],
                'revokes': [],
            },
        )

    body = response.json()
    assert body['status_code'] == ChannelPermissionDeniedError.Code
