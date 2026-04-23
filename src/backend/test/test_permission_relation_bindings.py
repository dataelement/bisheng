"""Regression tests for permission relation-model bindings."""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_admin_user():
    return SimpleNamespace(user_id=1, is_admin=lambda: True)


class TestRelationModelBindings:

    @pytest.mark.asyncio
    async def test_rebinding_same_relation_skips_tuple_write(self, mock_admin_user):
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

        mock_authorize.assert_not_awaited()
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
