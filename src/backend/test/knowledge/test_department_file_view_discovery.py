from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalFileBrowseReq,
    ShougangPortalHomeReq,
)
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessDecision,
    DepartmentFileAccessStatus,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)


def _service() -> KnowledgeSpaceService:
    return KnowledgeSpaceService(
        request=SimpleNamespace(headers={}),
        login_user=SimpleNamespace(
            user_id=9,
            user_name="申请人",
            tenant_id=1,
            is_admin=lambda: False,
        ),
    )


def test_portal_discovery_scope_is_explicit_and_backward_compatible() -> None:
    assert ShougangPortalFileBrowseReq().discovery_scope == "legacy"
    assert (
        ShougangPortalFileBrowseReq(discovery_scope="public_and_department").discovery_scope == "public_and_department"
    )
    assert ShougangPortalHomeReq(discovery_scope="public_and_department").discovery_scope == "public_and_department"


@pytest.mark.asyncio
async def test_public_and_department_scope_is_server_derived() -> None:
    service = _service()
    public_space = SimpleNamespace(
        id=1,
        name="公共库",
        type=KnowledgeTypeEnum.SPACE.value,
    )
    department_space = SimpleNamespace(
        id=3,
        name="部门库",
        type=KnowledgeTypeEnum.SPACE.value,
    )
    personal_space = SimpleNamespace(
        id=7,
        name="个人库",
        type=KnowledgeTypeEnum.SPACE.value,
    )
    binding = SimpleNamespace(
        space_id=3,
        department_id=30,
        tenant_id=1,
    )
    scope = SimpleNamespace(
        space_id=3,
        level=KnowledgeSpaceLevelEnum.DEPARTMENT,
        owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
        owner_id=30,
        tenant_id=1,
    )
    department = SimpleNamespace(
        id=30,
        tenant_id=1,
        status="active",
        is_deleted=0,
    )
    service._get_shougang_portal_visible_search_spaces = AsyncMock(
        side_effect=lambda requested_ids, _level: [personal_space] if requested_ids == [7] else []
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_space_ids_by_level",
            new=AsyncMock(return_value=[1]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_all",
            new=AsyncMock(return_value=[binding]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_map_by_space_ids",
            new=AsyncMock(return_value={3: scope}),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_ids",
            new=AsyncMock(return_value=[binding]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_ids",
            new=AsyncMock(return_value=[department]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids",
            new=AsyncMock(return_value=[public_space, department_space]),
        ),
    ):
        spaces = await service._get_shougang_portal_request_spaces(
            requested_space_ids=[],
            space_level=None,
            discovery_scope="public_and_department",
        )
        narrowed = await service._get_shougang_portal_request_spaces(
            requested_space_ids=[3, 999],
            space_level=None,
            discovery_scope="public_and_department",
        )
        preserved_personal = await service._get_shougang_portal_request_spaces(
            requested_space_ids=[7],
            space_level=None,
            discovery_scope="public_and_department",
        )

    assert [space.id for space in spaces] == [1, 3]
    assert [space.id for space in narrowed] == [3]
    assert [space.id for space in preserved_personal] == [7]


@pytest.mark.asyncio
async def test_department_files_remain_discoverable_with_batch_access_state() -> None:
    service = _service()
    files = [
        SimpleNamespace(id=101, knowledge_id=3),
        SimpleNamespace(id=102, knowledge_id=3),
        SimpleNamespace(id=103, knowledge_id=3),
    ]
    decisions = {
        101: DepartmentFileAccessDecision(
            file_id=101,
            space_id=3,
            status=DepartmentFileAccessStatus.APPROVAL_REQUIRED,
            can_download=True,
            department_id=30,
        ),
        102: DepartmentFileAccessDecision(
            file_id=102,
            space_id=3,
            status=DepartmentFileAccessStatus.ALLOWED,
            source="permission_template",
            department_id=30,
        ),
        103: DepartmentFileAccessDecision(
            file_id=103,
            space_id=3,
            status=DepartmentFileAccessStatus.UNAVAILABLE,
            department_id=30,
        ),
    }
    service.department_file_view_access_service = SimpleNamespace(evaluate_files=AsyncMock(return_value=decisions))
    service._get_shougang_portal_public_space_ids = AsyncMock(return_value=set())
    service._get_valid_department_space_ids = AsyncMock(return_value={3})

    visible = await service._filter_shougang_portal_visible_files(files)

    assert [file.id for file in visible] == [101, 102]
    assert service._portal_file_download_map[101] is True
    service.department_file_view_access_service.evaluate_files.assert_awaited_once()


def test_unauthorized_department_file_uses_strict_safe_projection() -> None:
    service = _service()
    service._portal_file_access_decision_map[101] = DepartmentFileAccessDecision(
        file_id=101,
        space_id=3,
        status=DepartmentFileAccessStatus.APPROVAL_REQUIRED,
        can_download=True,
        department_id=30,
    )
    service._portal_file_download_map[101] = True

    item = service._map_shougang_portal_file_item(
        3,
        {
            "id": 101,
            "file_name": "安全制度.pdf",
            "abstract": "敏感摘要",
            "knowledge_name": "部门库",
            "file_size": "10MB",
            "file_encoding": "internal-secret",
            "folder_path": "制度/安全",
            "source_path": "原始库>敏感路径/安全制度.pdf",
            "tags": [{"name": "制度", "resource_type": "space_file"}],
        },
    )

    assert item.content_access == "approval_required"
    assert item.can_download is True
    assert item.summary == ""
    assert item.file_size == ""
    assert item.file_encoding == ""
    assert item.source_path == ""
    assert item.folder_path == "制度/安全"
