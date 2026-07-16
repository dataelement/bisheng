from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from bisheng.common.errcode.knowledge_space import SpaceInvalidLevelError
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceFilePermissionsReq
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _service(*, is_admin: bool = False) -> KnowledgeSpaceService:
    login_user = SimpleNamespace(
        user_id=1,
        tenant_id=1,
        user_name="tester",
        is_admin=lambda: is_admin,
    )
    return KnowledgeSpaceService(MagicMock(), login_user)


def test_public_file_permission_request_rejects_duplicate_or_invalid_file_ids():
    with pytest.raises(ValidationError):
        KnowledgeSpaceFilePermissionsReq(file_ids=[1, 1])
    with pytest.raises(ValidationError):
        KnowledgeSpaceFilePermissionsReq(file_ids=[0])


@pytest.mark.asyncio
async def test_public_file_permission_batch_uses_child_permission_evaluator():
    service = _service()
    files = [
        SimpleNamespace(id=11, file_type=FileType.FILE.value),
        SimpleNamespace(id=12, file_type=FileType.FILE.value),
    ]
    context = {"permission_context": True}

    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(level=KnowledgeSpaceLevelEnum.PUBLIC),
        ),
        patch.object(service, "_get_space_files_or_raise", new_callable=AsyncMock, return_value=files),
        patch.object(service, "_build_child_permission_context", new_callable=AsyncMock, return_value=context),
        patch.object(service, "_filter_visible_child_items", new_callable=AsyncMock, return_value=files),
        patch.object(
            service,
            "_get_child_item_effective_permission_ids",
            new_callable=AsyncMock,
            side_effect=[
                {"view_file", "rename_file", "download_file", "manage_file_relation"},
                {"view_file"},
            ],
        ) as mock_effective_permissions,
    ):
        result = await service.get_public_space_file_permissions(7, [11, 12])

    assert result == {
        "permissions": [
            {
                "file_id": 11,
                "permission_ids": ["rename_file", "download_file", "manage_file_relation"],
            },
            {"file_id": 12, "permission_ids": []},
        ]
    }
    assert mock_effective_permissions.await_count == 2


@pytest.mark.asyncio
async def test_public_file_permission_batch_returns_folder_action_permissions():
    service = _service()
    folder = SimpleNamespace(id=21, file_type=FileType.DIR.value)
    context = {"permission_context": True}

    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(level=KnowledgeSpaceLevelEnum.PUBLIC),
        ),
        patch.object(service, "_get_space_files_or_raise", new_callable=AsyncMock, return_value=[folder]),
        patch.object(service, "_build_child_permission_context", new_callable=AsyncMock, return_value=context),
        patch.object(service, "_filter_visible_child_items", new_callable=AsyncMock, return_value=[folder]),
        patch.object(
            service,
            "_get_child_item_effective_permission_ids",
            new_callable=AsyncMock,
            return_value={
                "view_folder",
                "rename_folder",
                "download_folder",
                "delete_folder",
                "move_folder",
                "manage_folder_relation",
            },
        ),
    ):
        result = await service.get_public_space_file_permissions(7, [21])

    assert result == {
        "permissions": [
            {
                "file_id": 21,
                "permission_ids": [
                    "rename_folder",
                    "download_folder",
                    "delete_folder",
                    "move_folder",
                    "manage_folder_relation",
                ],
            }
        ]
    }


@pytest.mark.asyncio
async def test_public_file_permission_batch_grants_system_admin_without_child_lookup():
    service = _service(is_admin=True)
    files = [
        SimpleNamespace(id=11, file_type=FileType.FILE.value),
        SimpleNamespace(id=21, file_type=FileType.DIR.value),
    ]

    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(level=KnowledgeSpaceLevelEnum.PUBLIC),
        ),
        patch.object(service, "_get_space_files_or_raise", new_callable=AsyncMock, return_value=files),
        patch.object(service, "_build_child_permission_context", new_callable=AsyncMock) as mock_context,
    ):
        result = await service.get_public_space_file_permissions(7, [11, 21])

    assert result == {
        "permissions": [
            {
                "file_id": 11,
                "permission_ids": [
                    "rename_file",
                    "download_file",
                    "delete_file",
                    "move_file",
                    "manage_file_relation",
                ],
            },
            {
                "file_id": 21,
                "permission_ids": [
                    "rename_folder",
                    "download_folder",
                    "delete_folder",
                    "move_folder",
                    "manage_folder_relation",
                ],
            },
        ]
    }
    mock_context.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_file_permission_batch_rejects_non_public_space():
    service = _service()

    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(level=KnowledgeSpaceLevelEnum.TEAM),
        ),
        patch.object(service, "_get_space_files_or_raise", new_callable=AsyncMock) as mock_files,
    ):
        with pytest.raises(SpaceInvalidLevelError):
            await service.get_public_space_file_permissions(7, [11])

    mock_files.assert_not_awaited()
