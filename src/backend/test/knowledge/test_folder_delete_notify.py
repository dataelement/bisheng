"""Folder-delete department-admin inbox notification."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.approval.domain.services.approver_resolver import (
    resolve_folder_delete_notify_recipients,
)
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.department_admin_grant import DepartmentAdminGrantDao
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.services.knowledge_space_service import (
    FOLDER_DELETED_MESSAGE,
    KnowledgeSpaceService,
)


def _patch_primary_dept(monkeypatch, *, user_id: int, dept_id: int, path: str):
    async def fake_primary(uid: int):
        assert uid == user_id
        return SimpleNamespace(user_id=user_id, department_id=dept_id, is_primary=1)

    async def fake_dept(department_id: int):
        assert department_id == dept_id
        return SimpleNamespace(id=dept_id, path=path)

    monkeypatch.setattr(UserDepartmentDao, "aget_user_primary_department", fake_primary)
    monkeypatch.setattr(DepartmentDao, "aget_by_id", fake_dept)


@pytest.mark.asyncio
async def test_folder_delete_notify_sends_to_current_level_admins(monkeypatch):
    _patch_primary_dept(monkeypatch, user_id=41, dept_id=30, path="/10/20/30/")

    async def fake_admins(department_id: int):
        return {
            30: [3001, 3002],
            20: [2001],
            10: [1001],
        }.get(department_id, [])

    monkeypatch.setattr(DepartmentAdminGrantDao, "aget_user_ids_by_department", fake_admins)

    assert await resolve_folder_delete_notify_recipients(41) == [3001, 3002]


@pytest.mark.asyncio
async def test_folder_delete_notify_falls_back_to_parent_when_leaf_empty(monkeypatch):
    _patch_primary_dept(monkeypatch, user_id=41, dept_id=30, path="/10/20/30/")

    async def fake_admins(department_id: int):
        return {
            30: [],
            20: [2001, 2002],
            10: [1001],
        }.get(department_id, [])

    monkeypatch.setattr(DepartmentAdminGrantDao, "aget_user_ids_by_department", fake_admins)

    assert await resolve_folder_delete_notify_recipients(41) == [2001, 2002]


@pytest.mark.asyncio
async def test_folder_delete_notify_skips_level_when_operator_is_admin(monkeypatch):
    """Operator is leaf admin → skip whole leaf (including co-admins) → parent."""
    _patch_primary_dept(monkeypatch, user_id=3001, dept_id=30, path="/10/20/30/")

    async def fake_admins(department_id: int):
        return {
            30: [3001, 3002],  # operator is admin; co-admin 3002 must NOT receive
            20: [2001],
            10: [1001],
        }.get(department_id, [])

    monkeypatch.setattr(DepartmentAdminGrantDao, "aget_user_ids_by_department", fake_admins)

    assert await resolve_folder_delete_notify_recipients(3001) == [2001]


@pytest.mark.asyncio
async def test_folder_delete_notify_returns_empty_when_no_admins(monkeypatch):
    _patch_primary_dept(monkeypatch, user_id=41, dept_id=30, path="/10/20/30/")

    async def fake_admins(department_id: int):
        return []

    monkeypatch.setattr(DepartmentAdminGrantDao, "aget_user_ids_by_department", fake_admins)

    assert await resolve_folder_delete_notify_recipients(41) == []


@pytest.mark.asyncio
async def test_folder_delete_notify_returns_empty_without_primary_department(monkeypatch):
    async def fake_primary(uid: int):
        return None

    monkeypatch.setattr(UserDepartmentDao, "aget_user_primary_department", fake_primary)

    assert await resolve_folder_delete_notify_recipients(41) == []


@pytest.mark.asyncio
async def test_notify_folder_deleted_sends_inbox_message():
    login_user = SimpleNamespace(user_id=41, tenant_id=1, user_name="alice")
    message_service = MagicMock()
    message_service.send_generic_notify = AsyncMock()
    service = KnowledgeSpaceService(request=SimpleNamespace(), login_user=login_user)
    service.message_service = message_service

    with patch(
        "bisheng.approval.domain.services.approver_resolver.resolve_folder_delete_notify_recipients",
        new_callable=AsyncMock,
        return_value=[3001],
    ) as mock_resolve:
        await service._notify_folder_deleted(folder_name="测试文件夹", space_id=1)

    mock_resolve.assert_awaited_once_with(41)
    message_service.send_generic_notify.assert_awaited_once()
    call_kwargs = message_service.send_generic_notify.await_args.kwargs
    assert call_kwargs["receiver_user_ids"] == [3001]
    assert call_kwargs["action_code"] == FOLDER_DELETED_MESSAGE
    assert call_kwargs["sender"] == 41
    content = call_kwargs["content_item_list"]
    assert any(item.get("type") == "system_text" and item.get("content") == FOLDER_DELETED_MESSAGE for item in content)
    assert any(item.get("type") == "target" and item.get("content") == "测试文件夹" for item in content)


@pytest.mark.asyncio
async def test_delete_folder_invokes_notify_hook():
    login_user = SimpleNamespace(user_id=41, tenant_id=1, user_name="alice")
    service = KnowledgeSpaceService(request=SimpleNamespace(), login_user=login_user)

    folder = SimpleNamespace(
        id=91,
        knowledge_id=1,
        file_type=FileType.DIR.value,
        file_name="测试文件夹",
        file_level_path="",
    )
    # tenant_id=None skips PDF artifact snapshot path in delete_folder
    space = SimpleNamespace(id=1, tenant_id=None, type=3)

    with (
        patch.object(service, "_get_folder_for_action", new_callable=AsyncMock, return_value=folder),
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_children_by_prefix",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch",
            new_callable=AsyncMock,
        ),
        patch.object(service, "_cleanup_resource_tuples", new_callable=AsyncMock),
        patch.object(service, "update_folder_update_time", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
            new_callable=AsyncMock,
        ),
        patch.object(service, "_enqueue_recommendation_deleted_files"),
        patch.object(service, "_notify_folder_deleted", new_callable=AsyncMock) as mock_notify,
        patch(
            "bisheng.channel.domain.models.channel_knowledge_sync.ChannelKnowledgeSyncDao.adelete_by_folder_ids",
            new_callable=AsyncMock,
        ),
    ):
        await service.delete_folder(1, 91)

    mock_notify.assert_awaited_once_with(folder_name="测试文件夹", space_id=1)
