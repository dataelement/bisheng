from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.department.domain.services.local_member_personal_recycle import (
    LocalMemberPersonalRecycleResult,
    _pick_host_space_id,
    _resolve_folder_name,
    recycle_local_member_personal_knowledge_spaces,
)


def test_resolve_folder_name_uses_user_name_or_fallback():
    assert _resolve_folder_name("Alice", 42) == "Alice"
    assert _resolve_folder_name("  ", 42) == "user_42"


@pytest.mark.asyncio
async def test_recycle_skips_when_no_content():
    with (
        patch(
            "bisheng.department.domain.services.local_member_personal_recycle._pick_host_space_id",
            AsyncMock(return_value=10),
        ),
        patch(
            "bisheng.department.domain.services.local_member_personal_recycle._build_recycle_login_user",
            AsyncMock(return_value=SimpleNamespace(user_id=1, user_name="admin")),
        ),
        patch(
            "bisheng.department.domain.services.local_member_personal_recycle._count_active_files",
            AsyncMock(return_value=0),
        ),
    ):
        result = await recycle_local_member_personal_knowledge_spaces(
            user_id=42,
            user_name="Bob",
            space_ids=[10, 11],
            operator=SimpleNamespace(user_id=1),
        )

    assert result == LocalMemberPersonalRecycleResult(folder_name="Bob")


@pytest.mark.asyncio
async def test_recycle_moves_content_and_soft_deletes_batch():
    user_folder = SimpleNamespace(id=900, knowledge_id=10, file_level_path="")
    moved_file = SimpleNamespace(id=901, file_type=1)
    moved_folder = SimpleNamespace(id=902, file_type=0)

    space_service = SimpleNamespace(
        find_or_create_folder_for_file_sync=AsyncMock(return_value=user_folder),
        move_folder=AsyncMock(),
        move_file_folder=AsyncMock(),
    )
    recycle_service = SimpleNamespace(
        soft_delete_member_personal_batch=AsyncMock(return_value="batch-1"),
    )

    async def _count_active_files(space_id: int) -> int:
        return 2 if space_id == 10 else 0

    async def _list_root_items(space_id: int):
        assert space_id == 10
        return [moved_folder, moved_file]

    sync_metadata = AsyncMock()
    with (
        patch(
            "bisheng.department.domain.services.local_member_personal_recycle._pick_host_space_id",
            AsyncMock(return_value=10),
        ),
        patch(
            "bisheng.department.domain.services.local_member_personal_recycle._build_recycle_login_user",
            AsyncMock(return_value=SimpleNamespace(user_id=1, user_name="admin")),
        ),
        patch(
            "bisheng.department.domain.services.local_member_personal_recycle._count_active_files",
            side_effect=_count_active_files,
        ),
        patch(
            "bisheng.department.domain.services.local_member_personal_recycle._list_root_items",
            side_effect=_list_root_items,
        ),
        patch(
            "bisheng.department.domain.services.local_member_personal_recycle._collect_recycle_ids",
            AsyncMock(return_value=([901], [900, 902])),
        ),
        patch(
            "bisheng.department.domain.services.local_member_personal_recycle._sync_recycled_file_metadata",
            sync_metadata,
        ),
        patch(
            "bisheng.department.domain.services.local_member_personal_recycle.KnowledgeSpaceService",
            return_value=space_service,
        ),
        patch(
            "bisheng.department.domain.services.local_member_personal_recycle.KnowledgeRecycleService",
            return_value=recycle_service,
        ),
        patch(
            "bisheng.department.domain.services.local_member_personal_recycle.bypass_tenant_filter",
            nullcontext,
        ),
    ):
        result = await recycle_local_member_personal_knowledge_spaces(
            user_id=42,
            user_name="Bob",
            space_ids=[10, 11],
            operator=SimpleNamespace(user_id=1),
        )

    space_service.move_folder.assert_awaited_once_with(10, 902, 900)
    space_service.move_file_folder.assert_awaited_once_with(10, 901, 900)
    sync_metadata.assert_awaited_once()
    recycle_service.soft_delete_member_personal_batch.assert_awaited_once_with(
        recycle_root_id=900,
        file_ids=[901],
        folder_ids=[900, 902],
        list_entry_ids=[900],
    )
    assert result.performed is True
    assert result.recycled_count == 3
    assert result.folder_name == "Bob"
    assert result.recycle_batch_id == "batch-1"
    assert result.host_space_id == 10


@pytest.mark.asyncio
async def test_pick_host_space_prefers_non_favorite_with_more_files():
    spaces = {
        10: SimpleNamespace(id=10, is_favorite=True),
        20: SimpleNamespace(id=20, is_favorite=False),
    }

    async def _count_active_files(space_id: int) -> int:
        return {10: 5, 20: 5}[space_id]

    with (
        patch(
            "bisheng.department.domain.services.local_member_personal_recycle.KnowledgeDao.aquery_by_id",
            AsyncMock(side_effect=lambda sid: spaces[int(sid)]),
        ),
        patch(
            "bisheng.department.domain.services.local_member_personal_recycle._count_active_files",
            side_effect=_count_active_files,
        ),
    ):
        host_id = await _pick_host_space_id([10, 20])

    assert host_id == 20
