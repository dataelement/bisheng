import pytest
from unittest.mock import AsyncMock, patch

from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService as FGS,
)
from bisheng.permission.domain.services.permission_service import PermissionService


@pytest.mark.asyncio
async def test_precomputed_level_skips_get_permission_level():
    login_user = type('U', (), {'user_id': 7, 'is_admin': lambda self: False})()

    # Force the fallback branch: no tuples, no bindings -> empty effective set.
    with patch.object(FGS, 'get_relation_models_map', new_callable=AsyncMock, return_value={}), \
         patch('bisheng.permission.domain.services.fine_grained_permission_service._get_bindings',
               new_callable=AsyncMock, return_value=[]), \
         patch.object(FGS, 'get_current_user_subject_strings', new_callable=AsyncMock, return_value=set()), \
         patch.object(FGS, 'get_binding_department_paths', new_callable=AsyncMock, return_value={}), \
         patch.object(FGS, 'build_resource_lineage', new_callable=AsyncMock,
                      return_value=[('knowledge_space', '9')]), \
         patch.object(PermissionService, '_get_fga', return_value=None), \
         patch.object(PermissionService, 'get_implicit_permission_level',
                      new_callable=AsyncMock, return_value=None), \
         patch.object(FGS, '_public_knowledge_space_viewer_permission_ids',
                      new_callable=AsyncMock, return_value=set()), \
         patch.object(PermissionService, 'get_permission_level',
                      new_callable=AsyncMock) as spy_level:
        result = await FGS.get_effective_permission_ids_async(
            login_user, 'knowledge_space', '9',
            precomputed_permission_level='can_read',
        )
    # get_permission_level must NOT be called when a precomputed level is supplied.
    spy_level.assert_not_awaited()
    # 'can_read' maps to view_space default permissions -> non-empty
    assert 'view_space' in result


@pytest.mark.asyncio
async def test_without_precomputed_falls_back_to_get_permission_level():
    login_user = type('U', (), {'user_id': 7, 'is_admin': lambda self: False})()
    with patch.object(FGS, 'get_relation_models_map', new_callable=AsyncMock, return_value={}), \
         patch('bisheng.permission.domain.services.fine_grained_permission_service._get_bindings',
               new_callable=AsyncMock, return_value=[]), \
         patch.object(FGS, 'get_current_user_subject_strings', new_callable=AsyncMock, return_value=set()), \
         patch.object(FGS, 'get_binding_department_paths', new_callable=AsyncMock, return_value={}), \
         patch.object(FGS, 'build_resource_lineage', new_callable=AsyncMock,
                      return_value=[('knowledge_space', '9')]), \
         patch.object(PermissionService, '_get_fga', return_value=None), \
         patch.object(PermissionService, 'get_implicit_permission_level',
                      new_callable=AsyncMock, return_value=None), \
         patch.object(FGS, '_public_knowledge_space_viewer_permission_ids',
                      new_callable=AsyncMock, return_value=set()), \
         patch.object(PermissionService, 'get_permission_level',
                      new_callable=AsyncMock, return_value='can_read') as spy_level:
        result = await FGS.get_effective_permission_ids_async(login_user, 'knowledge_space', '9')
    spy_level.assert_awaited_once()
    assert 'view_space' in result
