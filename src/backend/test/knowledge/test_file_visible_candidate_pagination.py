"""F048 candidate-first visibility pagination for space files and folders."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.cursor import decode_cursor
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.services.permission_action_service import PermissionActor

_SERVICE = "bisheng.knowledge.domain.services.knowledge_space_service"


class _User:
    user_id = 41
    tenant_id = 7
    is_global_super = False

    def is_admin(self) -> bool:
        return False


class _SuperUser(_User):
    is_global_super = True


def _item(file_id: int, *, file_type: int = FileType.FILE.value) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        user_id=90,
        tenant_id=7,
        knowledge_id=9,
        file_name=f"item-{file_id}.pdf",
        file_type=file_type,
        file_level_path="",
        update_time=datetime(2026, 8, 13, 8, 0) + timedelta(seconds=file_id),
    )


async def test_candidate_batches_use_final_child_visible_not_parent_allow() -> None:
    service = KnowledgeSpaceService(request=None, login_user=_User())
    folder = _item(1, file_type=FileType.DIR.value)
    file_row = _item(2)
    actor = PermissionActor(user_id=41, current_tenant_id=7)
    visible_check = AsyncMock(return_value={"1": False, "2": True})
    actor_resolver = AsyncMock(return_value=actor)

    with (
        patch(
            f"{_SERVICE}.batch_check_business_visible",
            new=visible_check,
            create=True,
        ),
        patch.object(
            service,
            "_batch_actions",
            new=AsyncMock(side_effect=AssertionError("visible must use the no-admin-shortcut facade")),
        ),
        patch.object(service, "_permission_actor", new=actor_resolver),
    ):
        result = await service._filter_visible_child_items(
            [folder, file_row],
            space_id=9,
            context={"permissions": {("knowledge_space", "9"): {"visible"}}},
        )

    assert [row.id for row in result] == [2]
    assert visible_check.await_count == 2
    assert {call.kwargs["resource_type"] for call in visible_check.await_args_list} == {
        "folder",
        "knowledge_file",
    }
    actor_resolver.assert_awaited_once()
    assert all(call.kwargs["actor"] is actor for call in visible_check.await_args_list)


async def test_service_reuses_permission_actor_across_single_checks() -> None:
    service = KnowledgeSpaceService(request=None, login_user=_User())
    actor = PermissionActor(user_id=41, current_tenant_id=7)
    resolve_actor = AsyncMock(return_value=actor)
    check_action = AsyncMock(return_value=True)

    with (
        patch(f"{_SERVICE}.resolve_permission_actor", new=resolve_actor),
        patch(f"{_SERVICE}.check_business_action", new=check_action),
    ):
        assert await service._check_action("knowledge_space", 9, "visible") is True
        assert await service._check_action("folder", 11, "visible") is True

    resolve_actor.assert_awaited_once_with(service.login_user)
    assert check_action.await_count == 2
    assert all(call.kwargs["actor"] is actor for call in check_action.await_args_list)
    assert service._permission_actor_resolve_count == 1
    assert service._permission_actor_cache_hits == 1
    assert service._permission_actor_resolve_elapsed_ms >= 0


@pytest.mark.parametrize(
    ("allowed_ids", "page_size", "expected_ids", "expected_has_more", "expected_cursor_id"),
    [
        (set(range(1, 101)) - {5, 17}, 20, list(range(1, 5)) + list(range(6, 17)) + list(range(18, 23)), True, 22),
        ({60, 120, 180, 240}, 3, [60, 120, 180], True, 239),
        ({60, 120}, 3, [60, 120], False, None),
    ],
)
async def test_candidate_scan_refills_page_and_tracks_last_scanned_candidate(
    allowed_ids: set[int],
    page_size: int,
    expected_ids: list[int],
    expected_has_more: bool,
    expected_cursor_id: int | None,
) -> None:
    service = KnowledgeSpaceService(request=None, login_user=_User())
    candidates = [_item(file_id) for file_id in range(1, 251)]
    fetch_cursors: list[list | None] = []

    async def _fetch(*_args, cursor=None, page_size=100, **_kwargs):
        fetch_cursors.append(cursor)
        start_id = int(cursor[-1]) + 1 if cursor else 1
        return [row for row in candidates if row.id >= start_id][:page_size]

    async def _visible(items, **_kwargs):
        return [row for row in items if row.id in allowed_ids]

    metric = MagicMock()
    with (
        patch(f"{_SERVICE}.SpaceFileDao.async_list_children", new=AsyncMock(side_effect=_fetch)),
        patch.object(service, "_filter_visible_child_items", new=AsyncMock(side_effect=_visible)),
        patch(f"{_SERVICE}.emit_metric", new=metric, create=True),
    ):
        rows, has_more, scan_cursor = await service._scan_visible_child_items(
            space_id=9,
            parent_id=None,
            file_ids=None,
            order_field="file_type",
            order_sort="asc",
            file_status=None,
            file_type=None,
            page_size=page_size,
        )

    assert [row.id for row in rows] == expected_ids
    assert has_more is expected_has_more
    assert (scan_cursor[-1] if scan_cursor else None) == expected_cursor_id
    assert all(cursor is None or len(cursor) == 4 for cursor in fetch_cursors)
    metric.assert_called_once()
    assert metric.call_args.kwargs["scanned_candidates"] >= len(rows)
    assert metric.call_args.kwargs["returned_items"] == len(rows)
    assert metric.call_args.kwargs["batch_count"] == len(fetch_cursors)
    assert metric.call_args.kwargs["system_scope"] is False
    assert metric.call_args.kwargs["db_elapsed_ms"] >= 0
    assert metric.call_args.kwargs["permission_elapsed_ms"] >= 0
    assert metric.call_args.kwargs["total_elapsed_ms"] >= 0


async def test_list_cursor_uses_scan_boundary_and_is_retry_stable() -> None:
    service = KnowledgeSpaceService(request=None, login_user=_User())
    visible = _item(20)
    scan_boundary = [visible.file_type, 1, visible.update_time, 39]

    async def _call() -> str:
        with (
            patch.object(service, "_require_read_permission", new=AsyncMock()),
            patch.object(service, "_require_action", new=AsyncMock()),
            patch.object(
                service,
                "_scan_visible_child_items",
                new=AsyncMock(return_value=([visible], True, scan_boundary)),
            ),
            patch.object(service, "_enrich_with_version_info", new=AsyncMock()),
            patch.object(
                service,
                "_handle_file_folder_extra_info",
                new=AsyncMock(return_value=[{"id": visible.id}]),
            ),
        ):
            page = await service.list_space_children(space_id=9, page_size=1)
        assert page.next_cursor is not None
        return page.next_cursor

    first = await _call()
    second = await _call()
    assert first == second
    assert decode_cursor(
        first,
        expected_key_len=4,
        expected_context="space_children|order=file_type_asc",
    ) == [visible.file_type, 1, visible.update_time.isoformat(), 39]


async def test_root_children_reuses_space_authorization_and_scopes_version_query() -> None:
    service = KnowledgeSpaceService(request=None, login_user=_User())
    service.version_repo = MagicMock()
    service.version_repo.find_non_primary_file_ids_by_knowledge_ids = AsyncMock(return_value=[81])
    file_row = _item(2)
    require_read = AsyncMock()
    duplicate_action = AsyncMock(side_effect=AssertionError("root visible must not be checked twice"))
    scan = AsyncMock(return_value=([file_row], False, None))
    metric = MagicMock()

    with (
        patch.object(service, "_require_read_permission", new=require_read),
        patch.object(service, "_require_action", new=duplicate_action),
        patch.object(service, "_scan_visible_child_items", new=scan),
        patch.object(service, "_enrich_with_version_info", new=AsyncMock()),
        patch.object(
            service,
            "_handle_file_folder_extra_info",
            new=AsyncMock(return_value=[{"id": file_row.id}]),
        ),
        patch(f"{_SERVICE}.emit_metric", new=metric),
    ):
        page = await service.list_space_children(space_id=9, page_size=80)

    assert page.data == [{"id": file_row.id}]
    require_read.assert_awaited_once_with(9)
    duplicate_action.assert_not_awaited()
    service.version_repo.find_non_primary_file_ids_by_knowledge_ids.assert_awaited_once_with([9])
    assert scan.await_args.kwargs["exclude_file_ids"] == [81]
    metric.assert_called_once()
    assert metric.call_args.args == ("knowledge_space_children",)
    assert metric.call_args.kwargs["status"] == "success"
    assert metric.call_args.kwargs["returned_count"] == 1
    assert metric.call_args.kwargs["total_elapsed_ms"] >= 0
    assert metric.call_args.kwargs["scan_elapsed_ms"] >= 0


async def test_children_error_metric_identifies_failed_stage() -> None:
    service = KnowledgeSpaceService(request=None, login_user=_User())
    metric = MagicMock()

    with (
        patch.object(service, "_require_read_permission", new=AsyncMock()),
        patch.object(
            service,
            "_scan_visible_child_items",
            new=AsyncMock(side_effect=RuntimeError("test failure")),
        ),
        patch(f"{_SERVICE}.emit_metric", new=metric),
        pytest.raises(RuntimeError, match="test failure"),
    ):
        await service.list_space_children(space_id=9, page_size=80)

    metric.assert_called_once()
    assert metric.call_args.args == ("knowledge_space_children",)
    assert metric.call_args.kwargs["status"] == "error"
    assert metric.call_args.kwargs["failed_stage"] == "scan_visible"
    assert metric.call_args.kwargs["error_type"] == "RuntimeError"


async def test_super_admin_children_reads_business_rows_without_permission_checks() -> None:
    service = KnowledgeSpaceService(request=None, login_user=_SuperUser())
    file_row = _item(2)
    space = MagicMock(type=KnowledgeTypeEnum.SPACE.value)
    permission_call = AsyncMock(side_effect=AssertionError("super-admin listing must not check permission"))

    with (
        patch(f"{_SERVICE}.KnowledgeDao.aquery_by_id", new=AsyncMock(return_value=space)) as load_space,
        patch(
            f"{_SERVICE}.SpaceFileDao.async_list_children",
            new=AsyncMock(return_value=[file_row]),
        ) as list_children,
        patch.object(service, "_require_read_permission", new=permission_call),
        patch.object(service, "_require_action", new=permission_call),
        patch.object(service, "_require_folder_action", new=permission_call),
        patch.object(service, "_build_child_permission_context", new=permission_call),
        patch.object(service, "_filter_visible_child_items", new=permission_call),
        patch.object(service, "_enrich_with_version_info", new=AsyncMock()),
        patch.object(
            service,
            "_handle_file_folder_extra_info",
            new=AsyncMock(return_value=[{"id": file_row.id}]),
        ),
    ):
        page = await service.list_space_children(space_id=9, page_size=80)

    assert page.data == [{"id": file_row.id}]
    assert page.has_more is False
    load_space.assert_awaited_once_with(9)
    list_children.assert_awaited_once()
    permission_call.assert_not_awaited()


async def test_super_admin_search_reads_business_rows_without_permission_checks() -> None:
    service = KnowledgeSpaceService(request=None, login_user=_SuperUser())
    file_row = _item(2)
    space = MagicMock(type=KnowledgeTypeEnum.SPACE.value)
    permission_call = AsyncMock(side_effect=AssertionError("super-admin search must not check permission"))

    with (
        patch(f"{_SERVICE}.KnowledgeDao.aquery_by_id", new=AsyncMock(return_value=space)) as load_space,
        patch(
            f"{_SERVICE}.KnowledgeFileDao.aget_file_by_filters",
            new=AsyncMock(return_value=[file_row]),
        ) as list_files,
        patch.object(service, "_require_read_permission", new=permission_call),
        patch.object(service, "_require_action", new=permission_call),
        patch.object(service, "_require_folder_action", new=permission_call),
        patch.object(service, "_build_child_permission_context", new=permission_call),
        patch.object(service, "_filter_visible_child_items", new=permission_call),
        patch.object(service, "_enrich_with_version_info", new=AsyncMock()),
        patch.object(
            service,
            "_handle_file_folder_extra_info",
            new=AsyncMock(return_value=[{"id": file_row.id}]),
        ),
    ):
        result = await service.search_space_children(space_id=9, page_size=80)

    assert result == {
        "page": 1,
        "page_size": 80,
        "data": [{"id": file_row.id}],
        "has_more": False,
    }
    load_space.assert_awaited_once_with(9)
    list_files.assert_awaited_once()
    permission_call.assert_not_awaited()
