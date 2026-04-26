"""API-level integration tests for permission regressions.

These mount the real permission router on a minimal FastAPI app so we can
exercise request validation, dependency injection, and response envelopes
without requiring a full running backend.
"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from bisheng.core.openfga.exceptions import FGAWriteError
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.permission.api.router import router as permission_router
from bisheng.permission.domain.schemas.permission_schema import ResourcePermissionItem


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

    def test_create_relation_model_rejects_duplicate_name(self):
        app = _make_app(_AdminUser)
        state = [{
            'id': 'custom_existing',
            'name': '新关系测试',
            'relation': 'viewer',
            'grant_tier': 'usage',
            'permissions': ['view_app'],
            'permissions_explicit': True,
            'is_system': False,
        }]

        async def fake_get_relation_models():
            return deepcopy(state)

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            side_effect=fake_get_relation_models,
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_relation_models',
            new_callable=AsyncMock,
        ) as mock_save_relation_models:
            with TestClient(app) as client:
                create_resp = client.post(
                    '/api/v1/permissions/relation-models',
                    json={'name': ' 新关系测试 ', 'relation': 'viewer', 'permissions': ['view_app']},
                )
                body = create_resp.json()

        assert body['status_code'] == 19006
        mock_save_relation_models.assert_not_awaited()

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
            'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_effective_permission_ids_async',
            new_callable=AsyncMock,
            return_value=set(),
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

    def test_authorize_api_blocks_self_owner_revoke_when_it_is_the_last_owner(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value='owner',
        ), patch(
            'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_effective_permission_ids_async',
            new_callable=AsyncMock,
            return_value={'manage_app_owner'},
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions',
            new_callable=AsyncMock,
            return_value=[
                ResourcePermissionItem(
                    subject_type='user',
                    subject_id=7,
                    subject_name='viewer',
                    relation='owner',
                ),
            ],
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            with TestClient(app) as client:
                resp = client.post(
                    '/api/v1/permissions/resources/workflow/wf-1/authorize',
                    json={
                        'grants': [],
                        'revokes': [{
                            'subject_type': 'user',
                            'subject_id': 7,
                            'relation': 'owner',
                        }],
                    },
                )
                body = resp.json()

        assert body['status_code'] == 19000
        mock_authorize.assert_not_awaited()

    def test_authorize_api_allows_self_owner_revoke_when_another_owner_remains(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value='owner',
        ), patch(
            'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_effective_permission_ids_async',
            new_callable=AsyncMock,
            return_value={'manage_app_owner'},
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions',
            new_callable=AsyncMock,
            return_value=[
                ResourcePermissionItem(
                    subject_type='user',
                    subject_id=7,
                    subject_name='viewer',
                    relation='owner',
                ),
                ResourcePermissionItem(
                    subject_type='user',
                    subject_id=9,
                    subject_name='co-owner',
                    relation='owner',
                ),
            ],
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize, patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    '/api/v1/permissions/resources/workflow/wf-1/authorize',
                    json={
                        'grants': [],
                        'revokes': [{
                            'subject_type': 'user',
                            'subject_id': 7,
                            'relation': 'owner',
                        }],
                    },
                )
                body = resp.json()

        assert body['status_code'] == 200
        mock_authorize.assert_awaited_once()

    def test_permissions_list_requires_can_edit_on_resource(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.has_any_permission_async',
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_has_permission:
            with TestClient(app) as client:
                resp = client.get('/api/v1/permissions/resources/workflow/wf-1/permissions')
                body = resp.json()

        assert body['status_code'] == 19000
        mock_has_permission.assert_awaited_once()

    def test_knowledge_space_grant_subject_users_endpoint_returns_full_scope_candidates(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._has_resource_permission_management_access',
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._list_knowledge_space_grant_users',
            new_callable=AsyncMock,
            return_value=[{
                'user_id': 8,
                'user_name': 'Alice',
                'primary_department_path': '总部/研发部',
            }],
        ) as mock_list_users:
            with TestClient(app) as client:
                resp = client.get(
                    '/api/v1/permissions/resources/knowledge_space/1/grant-subjects/users',
                    params={'keyword': 'Ali'},
                )
                body = resp.json()

        assert body['status_code'] == 200
        assert body['data'][0]['user_name'] == 'Alice'
        mock_list_users.assert_awaited_once_with(keyword='Ali', page=1, page_size=1000)

    def test_knowledge_space_grant_subject_departments_endpoint_returns_full_tree(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._has_resource_permission_management_access',
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._list_knowledge_space_grant_departments',
            new_callable=AsyncMock,
            return_value=[{
                'id': 10,
                'dept_id': 'BS@10',
                'name': '研发部',
                'parent_id': None,
                'path': '/10/',
                'sort_order': 0,
                'source': 'local',
                'status': 'active',
                'member_count': 0,
                'children': [],
            }],
        ) as mock_list_departments:
            with TestClient(app) as client:
                resp = client.get(
                    '/api/v1/permissions/resources/knowledge_space/1/grant-subjects/departments',
                )
                body = resp.json()

        assert body['status_code'] == 200
        assert body['data'][0]['name'] == '研发部'
        mock_list_departments.assert_awaited_once()

    def test_workflow_grant_subject_departments_endpoint_uses_permission_access_not_department_admin(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._has_resource_permission_management_access',
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_has_access, patch(
            'bisheng.permission.api.endpoints.resource_permission._list_knowledge_space_grant_departments',
            new_callable=AsyncMock,
            return_value=[{
                'id': 10,
                'dept_id': 'BS@10',
                'name': '研发部',
                'parent_id': None,
                'path': '/10/',
                'sort_order': 0,
                'source': 'local',
                'status': 'active',
                'member_count': 0,
                'children': [],
            }],
        ) as mock_list_departments:
            with TestClient(app) as client:
                resp = client.get(
                    '/api/v1/permissions/resources/workflow/wf-1/grant-subjects/departments',
                )
                body = resp.json()

        assert body['status_code'] == 200
        assert body['data'][0]['name'] == '研发部'
        mock_has_access.assert_awaited_once()
        mock_list_departments.assert_awaited_once()

    def test_knowledge_space_grant_subject_user_groups_endpoint_returns_full_scope_groups(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._has_resource_permission_management_access',
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._list_knowledge_space_grant_user_groups',
            new_callable=AsyncMock,
            return_value=[{
                'id': 5,
                'group_name': '产品组',
            }],
        ) as mock_list_groups:
            with TestClient(app) as client:
                resp = client.get(
                    '/api/v1/permissions/resources/knowledge_space/1/grant-subjects/user-groups',
                    params={'keyword': '产品'},
                )
                body = resp.json()

        assert body['status_code'] == 200
        assert body['data'][0]['group_name'] == '产品组'
        mock_list_groups.assert_awaited_once_with(keyword='产品')

    def test_permissions_list_reads_workflow_permissions_after_fine_grained_allow(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.has_any_permission_async',
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_has_permission, patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions',
            new_callable=AsyncMock,
            return_value=[
                ResourcePermissionItem(
                    subject_type='user',
                    subject_id=7,
                    subject_name='viewer',
                    relation='owner',
                ),
            ],
        ) as mock_get_permissions, patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[],
        ):
            with TestClient(app) as client:
                resp = client.get('/api/v1/permissions/resources/workflow/wf-1/permissions')
                body = resp.json()

        assert body['status_code'] == 200
        assert body['data'][0]['subject_id'] == 7
        assert body['data'][0]['relation'] == 'owner'
        mock_has_permission.assert_awaited_once()
        mock_get_permissions.assert_awaited_once_with(
            object_type='workflow',
            object_id='wf-1',
        )

    def test_permissions_list_hides_legacy_subscription_viewer_tuple(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.has_any_permission_async',
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions',
            new_callable=AsyncMock,
            return_value=[
                ResourcePermissionItem(
                    subject_type='user',
                    subject_id=8,
                    subject_name='subscriber',
                    relation='viewer',
                ),
                ResourcePermissionItem(
                    subject_type='user',
                    subject_id=9,
                    subject_name='manager',
                    relation='manager',
                ),
            ],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[],
        ):
            with TestClient(app) as client:
                resp = client.get('/api/v1/permissions/resources/knowledge_space/1/permissions')
                body = resp.json()

        assert body['status_code'] == 200
        assert [item['subject_id'] for item in body['data']] == [9]

    def test_permissions_list_keeps_bound_viewer_grant(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.has_any_permission_async',
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions',
            new_callable=AsyncMock,
            return_value=[
                ResourcePermissionItem(
                    subject_type='user',
                    subject_id=8,
                    subject_name='explicit-viewer',
                    relation='viewer',
                ),
            ],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=[{
                'id': 'viewer',
                'name': '可查看',
                'relation': 'viewer',
                'grant_tier': 'usage',
                'permissions': [],
                'permissions_explicit': False,
                'is_system': True,
            }],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[{
                'key': 'knowledge_space:1:user:8:viewer:-',
                'resource_type': 'knowledge_space',
                'resource_id': '1',
                'subject_type': 'user',
                'subject_id': 8,
                'relation': 'viewer',
                'include_children': None,
                'model_id': 'viewer',
            }],
        ):
            with TestClient(app) as client:
                resp = client.get('/api/v1/permissions/resources/knowledge_space/1/permissions')
                body = resp.json()

        assert body['status_code'] == 200
        assert body['data'][0]['subject_id'] == 8
        assert body['data'][0]['model_id'] == 'viewer'

    def test_department_space_permissions_include_implicit_display_rows(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.has_any_permission_async',
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=[
                {
                    'id': 'manager',
                    'name': '可管理',
                    'relation': 'manager',
                    'grant_tier': 'manager',
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
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_space_id',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(department_id=10),
        ), patch(
            'bisheng.database.models.department.DepartmentDao.aget_by_id',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(id=10, name='财务部'),
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.get_implicit_permission_level',
            new_callable=AsyncMock,
            return_value='can_manage',
        ):
            with TestClient(app) as client:
                resp = client.get('/api/v1/permissions/resources/knowledge_space/101/permissions')
                body = resp.json()

        assert body['status_code'] == 200
        rows = {
            (item['subject_type'], item['subject_id']): item
            for item in body['data']
        }
        assert set(rows) == {
            ('department', 10),
            ('user', 7),
        }
        assert rows[('department', 10)]['relation'] == 'viewer'
        assert rows[('department', 10)]['model_id'] == 'viewer'
        assert rows[('department', 10)]['subject_name'] == '财务部'
        assert rows[('department', 10)]['include_children'] is False
        assert rows[('user', 7)]['relation'] == 'manager'
        assert rows[('user', 7)]['model_id'] == 'manager'
        assert rows[('user', 7)]['subject_name'] == 'viewer'

    def test_permission_check_uses_permission_id_for_all_resource_types(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.has_any_permission_async',
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_has_permission, patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.check',
            new_callable=AsyncMock,
        ) as mock_relation_check:
            with TestClient(app) as client:
                resp = client.post(
                    '/api/v1/permissions/check',
                    json={
                        'object_type': 'workflow',
                        'object_id': 'wf-1',
                        'relation': 'can_edit',
                        'permission_id': 'publish_app',
                    },
                )
                body = resp.json()

        assert body['status_code'] == 200
        assert body['data'] == {'allowed': True}
        mock_has_permission.assert_awaited_once()
        assert mock_has_permission.await_args.kwargs['object_type'] == 'workflow'
        assert mock_has_permission.await_args.kwargs['object_id'] == 'wf-1'
        assert mock_has_permission.await_args.kwargs['permission_ids'] == ['publish_app']
        mock_relation_check.assert_not_awaited()

    def test_authorize_api_requires_matching_management_permission_id(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=[
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
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value='can_manage',
        ), patch(
            'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_effective_permission_ids_async',
            new_callable=AsyncMock,
            return_value={'view_app', 'edit_app'},
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
                            'relation': 'viewer',
                            'model_id': 'viewer',
                        }],
                        'revokes': [],
                    },
                )
                body = resp.json()

        assert body['status_code'] == 19000
        mock_authorize.assert_not_awaited()

    def test_authorize_knowledge_space_uses_manage_permission_id_only(self):
        app = _make_app(_ViewerUser)

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=[
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
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value='can_read',
        ) as mock_get_permission_level, patch(
            'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_effective_permission_ids_async',
            new_callable=AsyncMock,
            return_value={'manage_space_relation'},
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize, patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    '/api/v1/permissions/resources/knowledge_space/1/authorize',
                    json={
                        'grants': [{
                            'subject_type': 'user',
                            'subject_id': 2,
                            'relation': 'viewer',
                            'model_id': 'viewer',
                        }],
                        'revokes': [],
                    },
                )
                body = resp.json()

        assert body['status_code'] == 200
        mock_authorize.assert_awaited_once()
        mock_get_permission_level.assert_not_awaited()

    def test_authorize_api_returns_tuple_write_error_when_fga_write_fails(self):
        app = _make_app(_AdminUser)

        with patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
            new_callable=AsyncMock,
            side_effect=FGAWriteError('boom'),
        ) as mock_authorize, patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ) as mock_save_bindings:
            with TestClient(app) as client:
                resp = client.post(
                    '/api/v1/permissions/resources/knowledge_library/12/authorize',
                    json={
                        'grants': [{
                            'subject_type': 'user',
                            'subject_id': 2,
                            'relation': 'owner',
                            'model_id': 'owner',
                        }],
                        'revokes': [{
                            'subject_type': 'user',
                            'subject_id': 2,
                            'relation': 'viewer',
                        }],
                    },
                )
                body = resp.json()

        assert body['status_code'] == 19004
        mock_authorize.assert_awaited_once()
        assert mock_authorize.await_args.kwargs['enforce_fga_success'] is True
        mock_save_bindings.assert_not_awaited()

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
        ), patch(
            'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_effective_permission_ids_async',
            new_callable=AsyncMock,
            return_value=set(),
        ):
            with TestClient(app) as client:
                resp = client.get(
                    '/api/v1/permissions/relation-models/grantable',
                    params={'object_type': 'workflow', 'object_id': 'wf-1'},
                )
                body = resp.json()

        assert body['status_code'] == 200
        assert body['data'] == []

    def test_grantable_knowledge_space_uses_manage_permission_id_only(self):
        app = _make_app(_ViewerUser)
        models = [
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
        ]

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=models,
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.get_permission_level',
            new_callable=AsyncMock,
            return_value='can_read',
        ) as mock_get_permission_level, patch(
            'bisheng.permission.domain.services.fine_grained_permission_service.FineGrainedPermissionService.get_effective_permission_ids_async',
            new_callable=AsyncMock,
            return_value={'manage_space_relation'},
        ):
            with TestClient(app) as client:
                resp = client.get(
                    '/api/v1/permissions/relation-models/grantable',
                    params={'object_type': 'knowledge_space', 'object_id': '1'},
                )
                body = resp.json()

        assert body['status_code'] == 200
        assert [item['id'] for item in body['data']] == ['owner', 'viewer']
        mock_get_permission_level.assert_not_awaited()
