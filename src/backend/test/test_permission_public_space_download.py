from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService,
)


@pytest.mark.asyncio
async def test_public_space_implicit_viewer_can_download_files_and_folders_only():
    login_user = SimpleNamespace(user_id=7)
    public_space = SimpleNamespace(
        id=1,
        type=KnowledgeTypeEnum.SPACE.value,
        space_level=KnowledgeSpaceLevelEnum.PUBLIC,
    )
    file_record = SimpleNamespace(
        id=120,
        knowledge_id=1,
        file_type=FileType.FILE.value,
        file_level_path='',
    )
    folder_record = SimpleNamespace(
        id=121,
        knowledge_id=1,
        file_type=FileType.DIR.value,
        file_level_path='',
    )

    async def query_file(file_id: int):
        return {
            120: file_record,
            121: folder_record,
        }.get(file_id)

    with patch.object(
        FineGrainedPermissionService,
        'get_relation_models_map',
        new_callable=AsyncMock,
        return_value={},
    ), patch(
        'bisheng.permission.domain.services.fine_grained_permission_service._get_bindings',
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        FineGrainedPermissionService,
        'get_current_user_subject_strings',
        new_callable=AsyncMock,
        return_value={'user:7'},
    ), patch(
        'bisheng.permission.domain.services.fine_grained_permission_service.PermissionService._get_fga',
        return_value=None,
    ), patch(
        'bisheng.permission.domain.services.fine_grained_permission_service.PermissionService.get_implicit_permission_level',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.permission.domain.services.fine_grained_permission_service.PermissionService.get_permission_level',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.query_by_id',
        new_callable=AsyncMock,
        side_effect=query_file,
    ), patch(
        'bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=public_space,
    ):
        assert await FineGrainedPermissionService.has_any_permission_async(
            login_user,
            'knowledge_file',
            120,
            ['download_file'],
        ) is True
        assert await FineGrainedPermissionService.has_any_permission_async(
            login_user,
            'folder',
            121,
            ['download_folder'],
        ) is True
        assert await FineGrainedPermissionService.has_any_permission_async(
            login_user,
            'knowledge_file',
            120,
            ['delete_file'],
        ) is False
        assert await FineGrainedPermissionService.has_any_permission_async(
            login_user,
            'folder',
            121,
            ['delete_folder'],
        ) is False
