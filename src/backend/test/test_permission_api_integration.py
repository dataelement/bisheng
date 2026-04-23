"""API-level integration tests for permission regressions.

These mount the real permission router on a minimal FastAPI app so we can
exercise request validation, dependency injection, and response envelopes
without requiring a full running backend.
"""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.permission.api.router import router as permission_router


class _AdminUser:
    user_id = 1
    user_name = 'admin'
    tenant_id = 1

    def is_admin(self):
        return True


class _ViewerUser:
    user_id = 7
    user_name = 'viewer'
    tenant_id = 1

    def is_admin(self):
        return False


def _make_app(user_factory):
    app = FastAPI()
    app.include_router(permission_router, prefix='/api/v1')

    async def get_user():
        return user_factory()

    app.dependency_overrides[UserPayload.get_login_user] = get_user
    return app


class TestPermissionApiIntegration:

    def test_relation_model_update_round_trip_preserves_explicit_empty_permissions(self):
        app = _make_app(_AdminUser)
        state = [{
            'id': 'custom_empty',
            'name': '空模型',
            'relation': 'viewer',
            'grant_tier': 'usage',
            'permissions': ['view_app'],
            'permissions_explicit': False,
            'is_system': False,
        }]

        async def fake_get_relation_models():
            return deepcopy(state)

        async def fake_save_relation_models(models):
            state.clear()
            state.extend(deepcopy(models))

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            side_effect=fake_get_relation_models,
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_relation_models',
            new_callable=AsyncMock,
            side_effect=fake_save_relation_models,
        ):
            with TestClient(app) as client:
                update_resp = client.put(
                    '/api/v1/permissions/relation-models/custom_empty',
                    json={'name': '仍然为空', 'permissions': []},
                )
                assert update_resp.json()['status_code'] == 200

                list_resp = client.get('/api/v1/permissions/relation-models')
                body = list_resp.json()

        assert body['status_code'] == 200
        assert body['data'] == [{
            'id': 'custom_empty',
            'name': '仍然为空',
            'relation': 'viewer',
            'grant_tier': 'usage',
            'permissions': [],
            'permissions_explicit': True,
            'is_system': False,
        }]

    def test_authorize_api_blocks_privilege_escalation_before_tuple_write(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=[
                {
                    'id': 'owner',
                    'name': '所有者',
                    'relation': 'owner',
                    'grant_tier': 'owner',
                    'permissions': [],
                    'permissions_explicit': False,
                    'is_system': True,
                },
            ],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value='can_read',
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            with TestClient(app) as client:
                resp = client.post(
                    '/api/v1/permissions/resources/workflow/wf-1/authorize',
                    json={
                        'grants': [{
                            'subject_type': 'user',
                            'subject_id': 2,
                            'relation': 'owner',
                        }],
                        'revokes': [],
                    },
                )
                body = resp.json()

        assert body['status_code'] == 19000
        mock_authorize.assert_not_awaited()

    def test_permissions_list_requires_can_edit_on_resource(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_check:
            with TestClient(app) as client:
                resp = client.get('/api/v1/permissions/resources/workflow/wf-1/permissions')
                body = resp.json()

        assert body['status_code'] == 19000
        mock_check.assert_awaited_once()

    def test_grantable_relation_models_returns_empty_for_read_only_caller(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=[
                {
                    'id': 'owner',
                    'name': '所有者',
                    'relation': 'owner',
                    'grant_tier': 'owner',
                    'permissions': [],
                    'permissions_explicit': False,
                    'is_system': True,
                },
                {
                    'id': 'viewer',
                    'name': '可查看',
                    'relation': 'viewer',
                    'grant_tier': 'usage',
                    'permissions': [],
                    'permissions_explicit': False,
                    'is_system': True,
                },
            ],
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value='can_read',
        ):
            with TestClient(app) as client:
                resp = client.get(
                    '/api/v1/permissions/relation-models/grantable',
                    params={'object_type': 'workflow', 'object_id': 'wf-1'},
                )
                body = resp.json()

        assert body['status_code'] == 200
        assert body['data'] == []
