from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.knowledge.domain.services.knowledge_mcp_query_service import KnowledgeMcpQueryService


def make_query(files=()):
    space = SimpleNamespace(id=1, name="space", type=3, tenant_id=7, state=1, is_favorite=False, description="")
    repo = SimpleNamespace(
        get_space=AsyncMock(return_value=space),
        find_by_id=AsyncMock(),
        scan_files=AsyncMock(return_value=list(files)),
        spaces=AsyncMock(return_value=[space]),
        content_matches=AsyncMock(return_value=set()),
    )

    async def permissions(kind, object_id, **kwargs):
        if kind == "knowledge_space":
            return {"view_space"}
        return {"view_file"} if object_id % 2 else set()

    owner = SimpleNamespace(
        login_user=SimpleNamespace(user_id=9, tenant_id=7),
        _get_effective_permission_ids=permissions,
        get_existing_portal_visible_space_levels=AsyncMock(return_value={1: "team"}),
    )
    return KnowledgeMcpQueryService(repo, owner), repo, owner


def item(file_id, **kwargs):
    return SimpleNamespace(
        id=file_id,
        knowledge_id=1,
        tenant_id=7,
        file_name=f"{file_id}.txt",
        file_type=1,
        status=2,
        file_level_path="",
        file_size=10,
        update_time=datetime(2026, 1, 1),
        user_id=9,
        entry_status=None,
        reference_document_id=None,
        **kwargs,
    )


async def test_visible_page_has_no_raw_count_and_cursor_is_bound_to_query():
    """AC-05, AC-17: denied files cannot distort a visible page or its cursor."""
    service, _repo, _ = make_query([item(5), item(4), item(3), item(2), item(1)])
    result = await service.list_files(knowledge_id=1, page_size=2)
    assert [row["id"] for row in result["data"]] == [5, 3]
    assert result["has_more"] and "total" not in result
    with pytest.raises(ValueError):
        await service.list_files(knowledge_id=1, page_size=2, sort_by="file_name", cursor=result["next_cursor"])
    assert not any(key in result["data"][0] for key in ("object_name", "user_metadata", "remark"))


async def test_cross_space_folder_is_denied_before_scanning():
    """AC-04: an ID in another space cannot expand a query."""
    service, repo, _ = make_query()
    repo.find_by_id.return_value = SimpleNamespace(id=20, knowledge_id=2, tenant_id=7, file_type=0)
    with pytest.raises(SpacePermissionDeniedError):
        await service.list_folders(knowledge_id=1, folder_id=20)
    repo.scan_files.assert_not_called()


async def test_root_read_permission_does_not_imply_upload_permission():
    """AC-03: writable discovery must inspect eligible folders before filtering."""
    service, repo, owner = make_query()
    folder = item(11)
    folder.file_type = 0
    repo.scan_files.return_value = [folder]

    async def permissions(kind, object_id, **kwargs):
        return {"view_folder", "upload_file_to_folder"} if kind == "folder" else {"view_space"}

    owner._get_effective_permission_ids = permissions
    result = await service.list_knowledge(writable_only=True)
    assert len(result["data"]) == 1
    assert not result["data"][0]["can_upload_to_root"]
    assert result["data"][0]["has_writable_folders"]


async def test_content_search_checks_permissions_before_reading_content():
    """AC-06: neither unauthorized IDs nor names are fed into content responses."""
    service, repo, _ = make_query([item(3), item(2)])
    repo.content_matches.return_value = {3}
    result = await service.search_files(keyword="policy", knowledge_ids=[1], search_mode="content")
    assert [row["id"] for row in result["data"]] == [3]
    assert [row.id for row in repo.content_matches.call_args.args[0]] == [3]


async def test_writable_filter_does_not_count_unreachable_folder_paths():
    """AC-03, AC-17: a hidden ancestor cannot make a space appear uploadable."""
    service, repo, owner = make_query()
    folder = item(11)
    folder.file_type, folder.file_level_path = 0, "/12"
    parent = item(12)
    parent.file_type = 0
    repo.scan_files.return_value = [folder]
    repo.find_by_id.return_value = parent

    async def permissions(kind, object_id, **kwargs):
        if kind == "knowledge_space":
            return {"view_space"}
        return {"view_folder", "upload_file_to_folder"} if object_id == 11 else set()

    owner._get_effective_permission_ids = permissions
    result = await service.list_knowledge(writable_only=True)
    assert result["data"] == []
