"""Regression tests for permission relation-model bindings."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mock_admin_user():
    return SimpleNamespace(user_id=1, is_admin=lambda: True)


class TestRelationModelBindings:

    def test_normalize_relation_model_name_strips_template_prefix(self):
        from bisheng.permission.api.endpoints.resource_permission import _normalize_model_dict

        assert _normalize_model_dict({
            'id': 'custom_view_space',
            'name': '知识空间模块查看空间',
            'relation': 'viewer',
            'grant_tier': 'usage',
            'permissions': ['view_space'],
            'permissions_explicit': True,
            'is_system': False,
        })['name'] == '查看空间'

        assert _normalize_model_dict({
            'id': 'custom_named',
            'name': '知识空间模块自定义模型',
            'relation': 'viewer',
            'grant_tier': 'usage',
            'permissions': ['view_space'],
            'permissions_explicit': True,
            'is_system': False,
        })['name'] == '知识空间模块自定义模型'

    @pytest.mark.asyncio
    async def test_update_relation_model_marks_explicit_empty_permissions(self, mock_admin_user):
        from bisheng.permission.api.endpoints.resource_permission import update_relation_model
        from bisheng.permission.domain.schemas.permission_schema import RelationModelUpdateRequest

        models = [{
            'id': 'custom_empty',
            'name': 'Empty',
            'relation': 'viewer',
            'grant_tier': 'usage',
            'permissions': ['view_app'],
            'permissions_explicit': False,
            'is_system': False,
        }]

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=models,
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_relation_models',
            new_callable=AsyncMock,
        ) as mock_save_relation_models:
            await update_relation_model(
                model_id='custom_empty',
                request=RelationModelUpdateRequest(name='Still Empty', permissions=[]),
                login_user=mock_admin_user,
            )

        saved = mock_save_relation_models.await_args.args[0]
        assert saved == [{
            'id': 'custom_empty',
            'name': 'Still Empty',
            'relation': 'viewer',
            'grant_tier': 'usage',
            'permissions': [],
            'permissions_explicit': True,
            'is_system': False,
        }]

    @pytest.mark.asyncio
    async def test_rebinding_same_relation_repairs_tuple_write(self, mock_admin_user):
        from bisheng.permission.api.endpoints.resource_permission import authorize_resource
        from bisheng.permission.domain.schemas.permission_schema import (
            AuthorizeGrantItem,
            AuthorizeRequest,
            AuthorizeRevokeItem,
        )

        request = AuthorizeRequest(
            grants=[
                AuthorizeGrantItem(
                    subject_type='user',
                    subject_id=2,
                    relation='viewer',
                    model_id='custom_viewer',
                ),
            ],
            revokes=[
                AuthorizeRevokeItem(
                    subject_type='user',
                    subject_id=2,
                    relation='viewer',
                ),
            ],
        )

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[{
                'key': 'workflow:1:user:2:viewer',
                'resource_type': 'workflow',
                'resource_id': '1',
                'subject_type': 'user',
                'subject_id': 2,
                'relation': 'viewer',
                'model_id': 'legacy_viewer',
            }],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ) as mock_save_bindings, patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            await authorize_resource(
                resource_type='workflow',
                resource_id='1',
                request=request,
                login_user=mock_admin_user,
            )

        mock_authorize.assert_awaited_once()
        assert mock_authorize.await_args.kwargs['grants'] == request.grants
        assert mock_authorize.await_args.kwargs['revokes'] == []
        assert mock_authorize.await_args.kwargs['enforce_fga_success'] is True
        saved = mock_save_bindings.await_args.args[0]
        assert saved == [{
            'key': 'workflow:1:user:2:viewer:-',
            'resource_type': 'workflow',
            'resource_id': '1',
            'subject_type': 'user',
            'subject_id': 2,
            'relation': 'viewer',
            'include_children': None,
            'model_id': 'custom_viewer',
        }]

    @pytest.mark.asyncio
    async def test_authorize_rejects_non_user_owner_grant(self, mock_admin_user):
        from bisheng.permission.api.endpoints.resource_permission import authorize_resource
        from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem, AuthorizeRequest

        request = AuthorizeRequest(
            grants=[
                AuthorizeGrantItem(
                    subject_type='department',
                    subject_id=3,
                    relation='owner',
                    model_id='owner',
                ),
            ],
        )

        with patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            resp = await authorize_resource(
                resource_type='workflow',
                resource_id='1',
                request=request,
                login_user=mock_admin_user,
            )

        assert resp.status_code == 19000
        mock_authorize.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_authorize_allows_invalid_owner_revoke_as_binding_cleanup(self, mock_admin_user):
        from bisheng.permission.api.endpoints.resource_permission import authorize_resource
        from bisheng.permission.domain.schemas.permission_schema import AuthorizeRequest, AuthorizeRevokeItem

        request = AuthorizeRequest(
            revokes=[
                AuthorizeRevokeItem(
                    subject_type='department',
                    subject_id=3,
                    relation='owner',
                    model_id='owner',
                ),
            ],
        )

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[{
                'key': 'workflow:1:department:3:owner:0',
                'resource_type': 'workflow',
                'resource_id': '1',
                'subject_type': 'department',
                'subject_id': 3,
                'relation': 'owner',
                'include_children': False,
                'model_id': 'owner',
            }],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ) as mock_save_bindings, patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            await authorize_resource(
                resource_type='workflow',
                resource_id='1',
                request=request,
                login_user=mock_admin_user,
            )

        mock_authorize.assert_not_awaited()
        assert mock_save_bindings.await_args.args[0] == []

    @pytest.mark.asyncio
    async def test_delete_relation_model_uses_bound_include_children(self, mock_admin_user):
        from bisheng.permission.api.endpoints.resource_permission import delete_relation_model

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=[{
                'id': 'custom_editor',
                'name': 'Custom Editor',
                'relation': 'editor',
                'grant_tier': 'usage',
                'permissions': [],
                'is_system': False,
            }],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[{
                'key': 'assistant:9:department:3:viewer:0',
                'resource_type': 'assistant',
                'resource_id': '9',
                'subject_type': 'department',
                'subject_id': 3,
                'relation': 'viewer',
                'include_children': False,
                'model_id': 'custom_editor',
            }],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_relation_models',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            await delete_relation_model(
                model_id='custom_editor',
                login_user=mock_admin_user,
            )

        revoke = mock_authorize.await_args.kwargs['revokes'][0]
        assert revoke.include_children is False

    @pytest.mark.asyncio
    async def test_delete_relation_model_skips_invalid_owner_revoke(self, mock_admin_user):
        from bisheng.permission.api.endpoints.resource_permission import delete_relation_model

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=[{
                'id': 'custom_owner',
                'name': 'Custom Owner',
                'relation': 'owner',
                'grant_tier': 'owner',
                'permissions': [],
                'is_system': False,
            }],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[{
                'key': 'assistant:9:department:3:owner:0',
                'resource_type': 'assistant',
                'resource_id': '9',
                'subject_type': 'department',
                'subject_id': 3,
                'relation': 'owner',
                'include_children': False,
                'model_id': 'custom_owner',
            }],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_relation_models',
            new_callable=AsyncMock,
        ) as mock_save_relation_models, patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ) as mock_save_bindings, patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ) as mock_authorize:
            await delete_relation_model(
                model_id='custom_owner',
                login_user=mock_admin_user,
            )

        mock_authorize.assert_not_awaited()
        assert mock_save_relation_models.await_args.args[0] == []
        assert mock_save_bindings.await_args.args[0] == []

    @pytest.mark.asyncio
    async def test_delete_relation_model_keeps_db_when_revoke_fails(self, mock_admin_user):
        from bisheng.core.openfga.exceptions import FGAWriteError
        from bisheng.permission.api.endpoints.resource_permission import delete_relation_model

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_relation_models',
            new_callable=AsyncMock,
            return_value=[{
                'id': 'custom_viewer',
                'name': 'Custom Viewer',
                'relation': 'viewer',
                'grant_tier': 'usage',
                'permissions': [],
                'is_system': False,
            }],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[{
                'key': 'workflow:9:user:3:viewer:-',
                'resource_type': 'workflow',
                'resource_id': '9',
                'subject_type': 'user',
                'subject_id': 3,
                'relation': 'viewer',
                'include_children': None,
                'model_id': 'custom_viewer',
            }],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_relation_models',
            new_callable=AsyncMock,
        ) as mock_save_relation_models, patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ) as mock_save_bindings, patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
            new_callable=AsyncMock,
            side_effect=FGAWriteError('boom'),
        ) as mock_authorize:
            resp = await delete_relation_model(
                model_id='custom_viewer',
                login_user=mock_admin_user,
            )

        assert resp.status_code == 19004
        mock_authorize.assert_awaited_once()
        assert mock_authorize.await_args.kwargs['enforce_fga_success'] is True
        mock_save_relation_models.assert_not_awaited()
        mock_save_bindings.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_bindings_migrates_legacy_knowledge_library_bindings(self):
        from bisheng.permission.api.endpoints.resource_permission import _get_bindings

        raw_bindings = [{
            'key': 'knowledge_space:12:user:7:viewer:-',
            'resource_type': 'knowledge_space',
            'resource_id': '12',
            'subject_type': 'user',
            'subject_id': 7,
            'relation': 'viewer',
            'include_children': None,
            'model_id': 'custom_viewer',
        }]

        with patch(
            'bisheng.permission.api.endpoints.resource_permission.ConfigDao.aget_config_by_key',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(value='[]'),
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission.json.loads',
            return_value=raw_bindings,
        ), patch(
            'bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aget_list_by_ids',
            new_callable=AsyncMock,
            return_value=[SimpleNamespace(id=12, type=0)],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ) as mock_save_bindings:
            result = await _get_bindings()

        assert result[0]['resource_type'] == 'knowledge_library'
        assert result[0]['resource_id'] == '12'
        assert result[0]['key'].startswith('knowledge_library:12:')
        mock_save_bindings.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_bindings_keeps_real_knowledge_space_bindings(self):
        from bisheng.permission.api.endpoints.resource_permission import _get_bindings

        raw_bindings = [{
            'key': 'knowledge_space:22:user:7:viewer:-',
            'resource_type': 'knowledge_space',
            'resource_id': '22',
            'subject_type': 'user',
            'subject_id': 7,
            'relation': 'viewer',
            'include_children': None,
            'model_id': 'custom_viewer',
        }]

        with patch(
            'bisheng.permission.api.endpoints.resource_permission.ConfigDao.aget_config_by_key',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(value='[]'),
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission.json.loads',
            return_value=raw_bindings,
        ), patch(
            'bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aget_list_by_ids',
            new_callable=AsyncMock,
            return_value=[SimpleNamespace(id=22, type=3)],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ) as mock_save_bindings:
            result = await _get_bindings()

        assert result[0]['resource_type'] == 'knowledge_space'
        assert result[0]['key'] == 'knowledge_space:22:user:7:viewer:-'
        mock_save_bindings.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_department_include_children_binding_flattens_generated_child_rows(self):
        from bisheng.permission.api.endpoints.resource_permission import (
            _apply_binding_metadata_to_permissions,
        )
        from bisheng.permission.domain.schemas.permission_schema import ResourcePermissionItem

        permissions = [
            ResourcePermissionItem(
                subject_type='department',
                subject_id=3,
                subject_name='研发部',
                relation='viewer',
                include_children=False,
            ),
            ResourcePermissionItem(
                subject_type='department',
                subject_id=4,
                subject_name='研发一组',
                relation='viewer',
                include_children=False,
            ),
            ResourcePermissionItem(
                subject_type='user_group',
                subject_id=8,
                subject_name='产品组',
                relation='editor',
            ),
        ]
        bindings = [
            {
                'key': 'assistant:9:department:3:viewer:1',
                'resource_type': 'assistant',
                'resource_id': '9',
                'subject_type': 'department',
                'subject_id': 3,
                'relation': 'viewer',
                'include_children': True,
                'model_id': 'viewer',
            },
            {
                'key': 'assistant:9:user_group:8:editor:-',
                'resource_type': 'assistant',
                'resource_id': '9',
                'subject_type': 'user_group',
                'subject_id': 8,
                'relation': 'editor',
                'include_children': None,
                'model_id': 'editor',
            },
        ]

        with patch(
            'bisheng.database.models.department.DepartmentDao.aget_by_id',
            new_callable=AsyncMock,
            return_value=SimpleNamespace(id=3, path='1.3'),
        ), patch(
            'bisheng.database.models.department.DepartmentDao.aget_subtree_ids',
            new_callable=AsyncMock,
            return_value=[3, 4],
        ):
            result = await _apply_binding_metadata_to_permissions(
                permissions,
                bindings,
                {
                    'viewer': {'name': '可查看'},
                    'editor': {'name': '可编辑'},
                },
            )

        assert [(item.subject_type, item.subject_id) for item in result] == [
            ('department', 3),
            ('department', 4),
            ('user_group', 8),
        ]
        assert result[0].include_children is True
        assert result[0].model_id == 'viewer'
        assert result[0].model_name == '可查看'
        assert result[1].include_children is False
        assert result[1].model_id == 'viewer'
        assert result[1].model_name == '可查看'
        assert result[2].model_id == 'editor'

    @pytest.mark.asyncio
    async def test_department_include_children_revoke_cleans_exact_and_subtree_bindings(self, mock_admin_user):
        from bisheng.permission.api.endpoints.resource_permission import authorize_resource
        from bisheng.permission.domain.schemas.permission_schema import AuthorizeRequest, AuthorizeRevokeItem

        request = AuthorizeRequest(
            revokes=[
                AuthorizeRevokeItem(
                    subject_type='department',
                    subject_id=3,
                    relation='viewer',
                    include_children=True,
                ),
            ],
        )

        with patch(
            'bisheng.permission.api.endpoints.resource_permission._get_bindings',
            new_callable=AsyncMock,
            return_value=[
                {
                    'key': 'assistant:9:department:3:viewer:1',
                    'resource_type': 'assistant',
                    'resource_id': '9',
                    'subject_type': 'department',
                    'subject_id': 3,
                    'relation': 'viewer',
                    'include_children': True,
                    'model_id': 'viewer',
                },
                {
                    'key': 'assistant:9:department:3:viewer:0',
                    'resource_type': 'assistant',
                    'resource_id': '9',
                    'subject_type': 'department',
                    'subject_id': 3,
                    'relation': 'viewer',
                    'include_children': False,
                    'model_id': 'viewer',
                },
                {
                    'key': 'assistant:9:user_group:8:editor:-',
                    'resource_type': 'assistant',
                    'resource_id': '9',
                    'subject_type': 'user_group',
                    'subject_id': 8,
                    'relation': 'editor',
                    'include_children': None,
                    'model_id': 'editor',
                },
            ],
        ), patch(
            'bisheng.permission.api.endpoints.resource_permission._save_bindings',
            new_callable=AsyncMock,
        ) as mock_save_bindings, patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.authorize',
            new_callable=AsyncMock,
        ):
            await authorize_resource(
                resource_type='assistant',
                resource_id='9',
                request=request,
                login_user=mock_admin_user,
            )

        saved = mock_save_bindings.await_args.args[0]
        assert saved == [{
            'key': 'assistant:9:user_group:8:editor:-',
            'resource_type': 'assistant',
            'resource_id': '9',
            'subject_type': 'user_group',
            'subject_id': 8,
            'relation': 'editor',
            'include_children': None,
            'model_id': 'editor',
        }]
