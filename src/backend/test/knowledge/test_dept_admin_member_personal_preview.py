"""Tests for dept-admin read-only preview of member personal knowledge spaces."""

from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus


def _install_schema_stubs() -> None:
    if "bisheng.common.services.base" not in sys.modules:
        base_service_stub = types.ModuleType("bisheng.common.services.base")
        base_service_stub.BaseService = type("BaseService", (), {})
        sys.modules["bisheng.common.services.base"] = base_service_stub


def _load_service_class():
    _install_schema_stubs()
    module = importlib.import_module("bisheng.knowledge.domain.services.knowledge_space_service")
    return module.KnowledgeSpaceService


def _make_login_user(user_id: int = 9) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name="dept-admin",
        tenant_id=1,
        is_admin=lambda: False,
        get_user_group_ids=AsyncMock(return_value=[]),
    )


def _make_personal_space(*, space_id: int = 165, owner_id: int = 42) -> Knowledge:
    return Knowledge(
        id=space_id,
        user_id=owner_id,
        name="Member Personal Space",
        type=KnowledgeTypeEnum.SPACE.value,
        description="",
        model="model-1",
        state=1,
    )


def _make_file(*, file_id: int = 1485, space_id: int = 165) -> SimpleNamespace:
    return SimpleNamespace(
        id=file_id,
        knowledge_id=space_id,
        user_id=42,
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        object_name="README.txt",
        file_name="README.txt",
    )


@pytest.fixture
def service():
    return _load_service_class()(MagicMock(), _make_login_user(user_id=9))


@pytest.mark.asyncio
async def test_get_space_info_allows_dept_admin_member_personal_preview(service):
    member_space = _make_personal_space(owner_id=42)
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=member_space),
        ),
        patch.object(
            service,
            "_get_effective_permission_ids",
            new=AsyncMock(return_value=set()),
        ),
        patch.object(
            service,
            "_can_dept_admin_preview_member_personal_space",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_count_space_members",
            new=AsyncMock(return_value=1),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_success_files_batch",
            new=AsyncMock(return_value={165: 1}),
        ),
        patch.object(service, "_decorate_auto_tag_for_info", new=AsyncMock()),
        patch.object(service, "_get_space_level", new=AsyncMock(return_value=KnowledgeSpaceLevelEnum.PERSONAL)),
    ):
        result = await service.get_space_info(165)

    assert result.id == 165
    assert result.user_name is not None


@pytest.mark.asyncio
async def test_get_space_info_denies_dept_admin_for_non_member_personal_space(service):
    member_space = _make_personal_space(owner_id=99)
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=member_space),
        ),
        patch.object(
            service,
            "_get_effective_permission_ids",
            new=AsyncMock(return_value=set()),
        ),
        patch.object(
            service,
            "_can_dept_admin_preview_member_personal_space",
            new=AsyncMock(return_value=False),
        ),
    ):
        with pytest.raises(SpacePermissionDeniedError):
            await service.get_space_info(165)


@pytest.mark.asyncio
async def test_get_file_preview_allows_dept_admin_read_only(service):
    file_record = _make_file()
    with (
        patch.object(service, "_get_file_for_action", new=AsyncMock(return_value=file_record)),
        patch.object(service, "_resolve_document_entry", new=AsyncMock(return_value=None)),
        patch.object(
            service,
            "_resolve_file_preview_access",
            new=AsyncMock(return_value=(True, False)),
        ),
        patch.object(service, "_log_file_preview_success", new=AsyncMock()),
        patch.object(service, "_log_portal_document_read_success", new=AsyncMock()),
        patch.object(service, "_is_portal_bff_proxy_request", return_value=False),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.get_file_share_detail",
            return_value={"preview_url": "/preview", "original_url": "/origin"},
        ),
    ):
        detail = await service.get_file_preview(1485)

    assert detail["can_download"] is False


@pytest.mark.asyncio
async def test_is_dept_admin_of_user_matches_subtree_membership():
    from bisheng.knowledge.domain.services.department_admin_member_access import is_dept_admin_of_user

    admin_dept = SimpleNamespace(id=10, path="1/10/")
    with (
        patch(
            "bisheng.knowledge.domain.services.department_admin_member_access.DepartmentDao.aget_user_admin_departments",
            new=AsyncMock(return_value=[admin_dept]),
        ),
        patch(
            "bisheng.knowledge.domain.services.department_admin_member_access.DepartmentDao.aget_subtree_ids",
            new=AsyncMock(return_value=[10, 11]),
        ),
        patch(
            "bisheng.knowledge.domain.services.department_admin_member_access.get_async_db_session",
        ) as mock_session_ctx,
    ):
        session = AsyncMock()
        session.exec = AsyncMock(return_value=SimpleNamespace(all=lambda: [42, 43]))
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

        assert await is_dept_admin_of_user(9, 42) is True
        assert await is_dept_admin_of_user(9, 999) is False


@pytest.mark.asyncio
async def test_get_file_preview_allows_dept_admin_before_document_entry_gate(service):
    file_record = _make_file()
    resolved_entry = SimpleNamespace(
        content_file_id=999,
        capabilities=SimpleNamespace(can_preview=False, can_download=False),
    )
    with (
        patch.object(service, "_get_file_for_action", new=AsyncMock(return_value=file_record)),
        patch.object(
            service,
            "_resolve_file_preview_access",
            new=AsyncMock(return_value=(True, False)),
        ),
        patch.object(service, "_resolve_document_entry", new=AsyncMock(return_value=resolved_entry)),
        patch.object(service, "_log_file_preview_success", new=AsyncMock()),
        patch.object(service, "_log_portal_document_read_success", new=AsyncMock()),
        patch.object(service, "_is_portal_bff_proxy_request", return_value=False),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.get_file_share_detail",
            return_value={"preview_url": "/preview", "original_url": "/origin"},
        ),
    ):
        detail = await service.get_file_preview(1485)

    assert detail["preview_url"] == "/preview"
    service._resolve_document_entry.assert_awaited_once_with(file_record, required_capability=None)
    from bisheng.knowledge.domain.services.department_admin_member_access import aget_member_personal_space_ids

    with patch(
        "bisheng.knowledge.domain.services.department_admin_member_access.get_async_db_session",
    ) as mock_session_ctx:
        session = AsyncMock()
        session.exec = AsyncMock(return_value=SimpleNamespace(all=lambda: [165, 167]))
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

        space_ids = await aget_member_personal_space_ids({42})

    assert space_ids == {165, 167}
