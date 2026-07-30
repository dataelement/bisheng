from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.core import database as core_database
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
from bisheng.knowledge.domain.services import knowledge_space_service as svc_mod
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessDecision,
    DepartmentFileAccessStatus,
)
from bisheng.knowledge.domain.services.knowledge_recycle_service import (
    KnowledgeRecycleService,
)


def _file(
    file_id: int,
    space_id: int = 7101,
    *,
    folder: bool = False,
    path: str = "",
    status: int = KnowledgeFileStatus.SUCCESS.value,
):
    item = SimpleNamespace(
        id=file_id,
        knowledge_id=space_id,
        file_type=FileType.DIR.value if folder else FileType.FILE.value,
        status=status,
        file_level_path=path,
        file_name=f"{'folder' if folder else 'file'}-{file_id}.md",
    )
    item.model_dump = lambda: {
        "id": item.id,
        "knowledge_id": item.knowledge_id,
        "file_type": item.file_type,
        "status": item.status,
        "file_level_path": item.file_level_path,
        "file_name": item.file_name,
    }
    return item


@pytest.mark.asyncio
async def test_resolve_qa_scope_file_ids_expands_folders_and_dedupes(monkeypatch):
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, user_name="tester")
    service.version_repo = None

    records = {
        3001: _file(3001, folder=True, path=""),
        9001: _file(9001),
        9002: _file(9002, path="/3001"),
    }

    async def _query_by_id(file_id):
        return records.get(file_id)

    async def _children_by_prefix(_space_id, prefix, file_status=None):
        assert prefix == "/3001"
        assert file_status == KnowledgeFileStatus.SUCCESS
        return [records[9001], records[9002]]

    monkeypatch.setattr(service, "_require_read_permission", AsyncMock())
    monkeypatch.setattr(service, "_require_permission_id", AsyncMock())
    monkeypatch.setattr(service, "_filter_visible_child_items", AsyncMock(side_effect=lambda items, **_kwargs: items))
    monkeypatch.setattr(svc_mod.KnowledgeFileDao, "query_by_id", _query_by_id)
    monkeypatch.setattr(svc_mod.SpaceFileDao, "get_children_by_prefix", _children_by_prefix)

    result = await service.resolve_qa_scope_file_ids(
        folder_refs=[SimpleNamespace(knowledge_space_id=7101, folder_id=3001)],
        file_refs=[SimpleNamespace(knowledge_space_id=7101, file_id=9001)],
        max_files=20,
    )

    assert result == {7101: [9001, 9002]}
    service._require_permission_id.assert_any_await("folder", 3001, "view_folder", space_id=7101)
    service._require_permission_id.assert_any_await("knowledge_file", 9001, "view_file", space_id=7101)


@pytest.mark.asyncio
async def test_resolve_qa_scope_file_ids_rejects_more_than_twenty_files(monkeypatch):
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, user_name="tester")
    service.version_repo = None
    folder = _file(3001, folder=True, path="")
    files = [_file(9100 + idx, path="/3001") for idx in range(21)]

    async def _query_by_id(file_id):
        return folder if file_id == 3001 else None

    async def _children_by_prefix(_space_id, _prefix, file_status=None):
        return files

    monkeypatch.setattr(service, "_require_read_permission", AsyncMock())
    monkeypatch.setattr(service, "_require_permission_id", AsyncMock())
    monkeypatch.setattr(service, "_filter_visible_child_items", AsyncMock(side_effect=lambda items, **_kwargs: items))
    monkeypatch.setattr(svc_mod.KnowledgeFileDao, "query_by_id", _query_by_id)
    monkeypatch.setattr(svc_mod.SpaceFileDao, "get_children_by_prefix", _children_by_prefix)

    with pytest.raises(ValueError, match="一次最多可选择20个文件进行问答。"):
        await service.resolve_qa_scope_file_ids(
            folder_refs=[SimpleNamespace(knowledge_space_id=7101, folder_id=3001)],
            file_refs=[],
            max_files=20,
        )


@pytest.mark.asyncio
async def test_portal_qa_tree_keeps_unauthorized_department_file_disabled(
    monkeypatch,
):
    service = svc_mod.KnowledgeSpaceService(
        request=SimpleNamespace(headers={}),
        login_user=SimpleNamespace(user_id=7, user_name="tester"),
    )
    denied_file = _file(9301, space_id=7103)
    service.department_file_view_access_service = SimpleNamespace(
        evaluate_files=AsyncMock(
            return_value={
                9301: DepartmentFileAccessDecision(
                    file_id=9301,
                    space_id=7103,
                    status=DepartmentFileAccessStatus.APPROVAL_REQUIRED,
                    department_id=33,
                )
            }
        )
    )
    monkeypatch.setattr(
        service,
        "_get_shougang_portal_qa_space",
        AsyncMock(return_value=(SimpleNamespace(id=7103), True)),
    )
    monkeypatch.setattr(
        service,
        "_resolve_shougang_portal_source_paths",
        AsyncMock(return_value=({9301: "部门库/检修"}, {})),
    )
    monkeypatch.setattr(
        svc_mod.SpaceFileDao,
        "async_list_children",
        AsyncMock(return_value=[denied_file]),
    )
    enrich = AsyncMock(side_effect=AssertionError("未授权文件不得加载标签或分享来源元数据"))
    monkeypatch.setattr(service, "_handle_file_folder_extra_info", enrich)

    result = await service.list_shougang_portal_qa_children(
        space_id=7103,
        parent_id=None,
        cursor=None,
        page_size=10,
        discovery_scope="public_and_department",
    )

    assert result["data"] == [
        {
            "id": 9301,
            "knowledge_id": 7103,
            "parent_id": None,
            "file_name": "file-9301.md",
            "file_type": FileType.FILE.value,
            "status": KnowledgeFileStatus.SUCCESS.value,
            "folder_path": "部门库/检修",
            "file_ext": "md",
            "selectable": False,
            "disabled_reason": "申请后可用于问答",
            "has_children": False,
            "resolved_file_count": 0,
            "content_access": "approval_required",
            "can_download": False,
            "is_department_file": True,
        }
    ]
    enrich.assert_not_awaited()


@pytest.mark.asyncio
async def test_portal_qa_tree_exposes_readonly_tags_and_share_source_for_authorized_member(
    monkeypatch,
):
    service = svc_mod.KnowledgeSpaceService(
        request=SimpleNamespace(headers={}),
        login_user=SimpleNamespace(user_id=7, user_name="tester"),
    )
    allowed_file = _file(9302, space_id=7103)
    denied_file = _file(9303, space_id=7103)
    service.department_file_view_access_service = SimpleNamespace(
        evaluate_files=AsyncMock(
            return_value={
                9302: DepartmentFileAccessDecision(
                    file_id=9302,
                    space_id=7103,
                    status=DepartmentFileAccessStatus.ALLOWED,
                    department_id=33,
                    can_download=False,
                ),
                9303: DepartmentFileAccessDecision(
                    file_id=9303,
                    space_id=7103,
                    status=DepartmentFileAccessStatus.APPROVAL_REQUIRED,
                    department_id=33,
                    can_download=False,
                ),
            }
        )
    )
    monkeypatch.setattr(
        service,
        "_get_shougang_portal_qa_space",
        AsyncMock(return_value=(SimpleNamespace(id=7103), True)),
    )
    monkeypatch.setattr(
        service,
        "_resolve_shougang_portal_source_paths",
        AsyncMock(return_value=({9302: "接收知识库", 9303: "接收知识库"}, {})),
    )
    monkeypatch.setattr(
        svc_mod.SpaceFileDao,
        "async_list_children",
        AsyncMock(return_value=[allowed_file, denied_file]),
    )
    enrich = AsyncMock(
        return_value=[
            {
                **allowed_file.model_dump(),
                "entry_type": "share",
                "tags": [{"id": 8, "tag_name": "AI标签"}],
                "file_size": 2048,
                "version_no": 3,
                "capabilities": {
                    "can_view": True,
                    "can_preview": True,
                    "can_download": False,
                    "can_move": True,
                    "can_manage_members": True,
                    "can_edit_content": False,
                    "can_publish": False,
                    "can_share": False,
                    "can_delete": True,
                },
                "user_name": "分享人",
                "updater_name": "修改人",
                "source_department_name": "来源部门",
                "source_space_id": 7001,
                "source_space_name": "来源知识库",
                "source_path": "来源知识库>源目录/file-9302.md",
            }
        ]
    )
    monkeypatch.setattr(service, "_handle_file_folder_extra_info", enrich)

    result = await service.list_shougang_portal_qa_children(
        space_id=7103,
        parent_id=None,
        cursor=None,
        page_size=10,
        discovery_scope="public_and_department",
    )

    item = result["data"][0]
    assert item["content_access"] == "allowed"
    assert item["folder_path"] == "接收知识库"
    assert item["entry_type"] == "share"
    assert item["tags"] == [{"id": 8, "tag_name": "AI标签"}]
    assert item["file_size"] == 2048
    assert item["version_no"] == 3
    assert item["capabilities"]["can_edit_content"] is False
    assert item["capabilities"]["can_publish"] is False
    assert item["capabilities"]["can_share"] is False
    assert item["user_name"] == "分享人"
    assert item["updater_name"] == "修改人"
    assert item["source_department_name"] == "来源部门"
    assert item["source_space_id"] == 7001
    assert item["source_space_name"] == "来源知识库"
    assert item["source_path"] == "来源知识库>源目录/file-9302.md"
    assert "share_source_file_id" not in item
    denied_item = result["data"][1]
    assert denied_item["content_access"] == "approval_required"
    assert "tags" not in denied_item
    assert "entry_type" not in denied_item
    assert "source_path" not in denied_item
    enrich.assert_awaited_once_with(
        [allowed_file],
        include_folder_counts=False,
        enrich_files=True,
    )


@pytest.mark.asyncio
async def test_portal_qa_unauthorized_explicit_file_returns_empty_scope(
    monkeypatch,
):
    service = svc_mod.KnowledgeSpaceService(
        request=SimpleNamespace(headers={}),
        login_user=SimpleNamespace(user_id=7, user_name="tester"),
    )
    service.version_repo = None
    denied_file = _file(9301, space_id=7103)
    monkeypatch.setattr(service, "_require_read_permission", AsyncMock())
    monkeypatch.setattr(
        service,
        "_require_permission_id",
        AsyncMock(side_effect=SpacePermissionDeniedError()),
    )
    monkeypatch.setattr(
        svc_mod.KnowledgeFileDao,
        "aget_file_by_ids",
        AsyncMock(return_value=[denied_file]),
    )

    result = await service.resolve_shougang_portal_qa_scope_file_ids(
        mode="files",
        knowledge_space_ids=[7103],
        folder_refs=[],
        file_refs=[
            SimpleNamespace(
                knowledge_space_id=7103,
                file_id=9301,
            )
        ],
        max_files=20,
    )

    assert result == {}


@pytest.mark.asyncio
async def test_portal_qa_explicit_durable_file_requires_workbench_view_permission(
    monkeypatch,
):
    service = svc_mod.KnowledgeSpaceService(
        request=SimpleNamespace(headers={}),
        login_user=SimpleNamespace(
            user_id=7,
            user_name="tester",
            tenant_id=1,
        ),
    )
    service.version_repo = None
    durable_file = _file(8301, space_id=7101)
    entry_file = _file(9301, space_id=7101)
    durable_resolver = AsyncMock(
        return_value=SimpleNamespace(entry_file_id=9301),
    )
    service.document_durable_reference_resolver = SimpleNamespace(
        resolve=durable_resolver,
    )
    require_permission = AsyncMock()
    monkeypatch.setattr(service, "_require_read_permission", AsyncMock())
    monkeypatch.setattr(
        service,
        "_require_permission_id",
        require_permission,
    )
    monkeypatch.setattr(
        svc_mod.KnowledgeFileDao,
        "aget_file_by_ids",
        AsyncMock(return_value=[durable_file]),
    )
    monkeypatch.setattr(
        svc_mod.KnowledgeFileDao,
        "query_by_id",
        AsyncMock(return_value=entry_file),
    )

    result = await service.resolve_shougang_portal_qa_scope_file_ids(
        mode="files",
        knowledge_space_ids=[7101],
        folder_refs=[],
        file_refs=[
            SimpleNamespace(
                knowledge_space_id=7101,
                file_id=8301,
            )
        ],
        max_files=20,
    )

    assert result == {7101: [9301]}
    durable_resolver.assert_awaited_once_with(
        tenant_id=1,
        requested_space_id=7101,
        durable_file_id=8301,
        require_view_permission=True,
    )
    require_permission.assert_awaited_once_with(
        "knowledge_file",
        9301,
        "view_file",
        space_id=7101,
    )


@pytest.mark.asyncio
async def test_portal_qa_empty_whole_space_returns_empty_scope(
    monkeypatch,
):
    service = svc_mod.KnowledgeSpaceService(
        request=SimpleNamespace(headers={}),
        login_user=SimpleNamespace(user_id=7, user_name="tester"),
    )
    service.version_repo = None
    load_files = AsyncMock(return_value=[])
    require_space = AsyncMock(return_value=SimpleNamespace(id=7101))
    monkeypatch.setattr(service, "_require_read_permission", require_space)
    monkeypatch.setattr(
        service,
        "_filter_visible_child_items",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        svc_mod.KnowledgeFileDao,
        "aget_file_by_filters",
        load_files,
    )

    result = await service.resolve_shougang_portal_qa_scope_file_ids(
        mode="knowledge_space",
        knowledge_space_ids=[7101],
        folder_refs=[],
        file_refs=[],
        max_files=20,
    )

    assert result == {}
    require_space.assert_awaited_once_with(7101)
    load_files.assert_awaited_once_with(
        7101,
        status=[KnowledgeFileStatus.SUCCESS.value],
        file_type=FileType.FILE.value,
    )


@pytest.mark.asyncio
async def test_portal_qa_whole_space_keeps_only_visible_current_success_files(
    monkeypatch,
):
    service = svc_mod.KnowledgeSpaceService(
        request=SimpleNamespace(headers={}),
        login_user=SimpleNamespace(user_id=7, user_name="tester"),
    )
    success_file = _file(9001)
    non_primary_file = _file(9002)
    recycled_file = _file(9003)
    processing_file = _file(
        9004,
        status=KnowledgeFileStatus.PROCESSING.value,
    )
    service.version_repo = SimpleNamespace(
        find_non_primary_file_ids_by_knowledge_ids=AsyncMock(
            return_value=[9002],
        )
    )
    monkeypatch.setattr(service, "_require_read_permission", AsyncMock())
    visibility_filter = AsyncMock(return_value=[success_file])
    monkeypatch.setattr(
        service,
        "_filter_visible_child_items",
        visibility_filter,
    )
    monkeypatch.setattr(
        svc_mod.KnowledgeFileDao,
        "aget_file_by_filters",
        AsyncMock(
            return_value=[
                success_file,
                non_primary_file,
                recycled_file,
                processing_file,
            ]
        ),
    )
    monkeypatch.setattr(
        KnowledgeRecycleService,
        "list_recycled_file_ids",
        AsyncMock(return_value=[9003]),
    )

    result = await service.resolve_shougang_portal_qa_scope_file_ids(
        mode="knowledge_space",
        knowledge_space_ids=[7101],
        folder_refs=[],
        file_refs=[],
        max_files=20,
    )

    assert result == {7101: [9001]}
    visibility_filter.assert_awaited_once_with(
        [success_file],
        space_id=7101,
    )


@pytest.mark.asyncio
async def test_portal_qa_inaccessible_space_returns_empty_scope(
    monkeypatch,
):
    service = svc_mod.KnowledgeSpaceService(
        request=SimpleNamespace(headers={}),
        login_user=SimpleNamespace(user_id=7, user_name="tester"),
    )
    file = _file(9301, space_id=7103)
    monkeypatch.setattr(
        service,
        "_require_read_permission",
        AsyncMock(side_effect=SpacePermissionDeniedError()),
    )
    monkeypatch.setattr(
        svc_mod.KnowledgeFileDao,
        "aget_file_by_filters",
        AsyncMock(return_value=[file]),
    )

    result = await service.resolve_shougang_portal_qa_scope_file_ids(
        mode="knowledge_space",
        knowledge_space_ids=[7103],
        folder_refs=[],
        file_refs=[],
        max_files=20,
    )

    assert result == {}


@pytest.mark.asyncio
async def test_portal_qa_folder_scope_filters_to_authorized_department_files(
    monkeypatch,
):
    service = svc_mod.KnowledgeSpaceService(
        request=SimpleNamespace(headers={}),
        login_user=SimpleNamespace(user_id=7, user_name="tester"),
    )
    service.version_repo = None
    folder = _file(3001, space_id=7103, folder=True)
    allowed_file = _file(9301, space_id=7103, path="/3001")
    denied_file = _file(9302, space_id=7103, path="/3001")
    monkeypatch.setattr(service, "_require_read_permission", AsyncMock())
    monkeypatch.setattr(
        service,
        "_require_permission_id",
        AsyncMock(),
    )
    monkeypatch.setattr(
        service,
        "_filter_visible_child_items",
        AsyncMock(return_value=[allowed_file]),
    )
    monkeypatch.setattr(
        svc_mod.KnowledgeFileDao,
        "aget_file_by_ids",
        AsyncMock(return_value=[folder]),
    )
    monkeypatch.setattr(
        svc_mod.SpaceFileDao,
        "get_children_by_prefix",
        AsyncMock(return_value=[allowed_file, denied_file]),
    )
    monkeypatch.setattr(
        KnowledgeRecycleService,
        "list_recycled_file_ids",
        AsyncMock(return_value=[]),
    )

    result = await service.resolve_shougang_portal_qa_scope_file_ids(
        mode="files",
        knowledge_space_ids=[7103],
        folder_refs=[
            SimpleNamespace(
                knowledge_space_id=7103,
                folder_id=3001,
            )
        ],
        file_refs=[],
        max_files=20,
    )

    assert result == {7103: [9301]}
    service._require_permission_id.assert_awaited_once_with(
        "folder",
        3001,
        "view_folder",
        space_id=7103,
    )


@pytest.mark.asyncio
async def test_portal_department_folder_stats_separate_discoverable_and_authorized_counts(
    monkeypatch,
):
    service = svc_mod.KnowledgeSpaceService(
        request=SimpleNamespace(headers={}),
        login_user=SimpleNamespace(user_id=7, user_name="tester"),
    )
    folder = _file(3001, space_id=7103, folder=True)
    allowed_file = _file(9301, space_id=7103, path="/3001")
    denied_file = _file(9302, space_id=7103, path="/3001")
    service.department_file_view_access_service = SimpleNamespace(
        evaluate_files=AsyncMock(
            return_value={
                9301: DepartmentFileAccessDecision(
                    file_id=9301,
                    space_id=7103,
                    status=DepartmentFileAccessStatus.ALLOWED,
                    source="approval_grant",
                    department_id=33,
                ),
                9302: DepartmentFileAccessDecision(
                    file_id=9302,
                    space_id=7103,
                    status=DepartmentFileAccessStatus.APPROVAL_REQUIRED,
                    department_id=33,
                ),
            }
        )
    )
    monkeypatch.setattr(
        service,
        "_get_shougang_portal_qa_space",
        AsyncMock(return_value=(SimpleNamespace(id=7103), True)),
    )
    monkeypatch.setattr(
        svc_mod.KnowledgeFileDao,
        "aget_file_by_ids",
        AsyncMock(return_value=[folder]),
    )
    monkeypatch.setattr(
        svc_mod.SpaceFileDao,
        "get_children_by_prefix",
        AsyncMock(return_value=[allowed_file, denied_file]),
    )

    result = await service.get_shougang_portal_qa_folder_stats(
        space_id=7103,
        folder_ids=[3001],
        discovery_scope="public_and_department",
    )

    assert result == {
        "stats": [
            {
                "folder_id": 3001,
                "file_num": 2,
                "success_file_num": 2,
                "resolved_file_count": 1,
            }
        ]
    }


@pytest.mark.asyncio
async def test_folder_extra_info_uses_visible_success_file_count(monkeypatch):
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    folder = _file(3001, folder=True, path="")
    visible_file = _file(9001, path="/3001")
    hidden_file = _file(9002, path="/3001")

    class _ExecResult:
        def all(self):
            return [(KnowledgeFileStatus.SUCCESS.value, 2)]

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def exec(self, _statement):
            return _ExecResult()

    async def _children_by_prefix(space_id, prefix, file_status=None):
        assert space_id == 7101
        assert prefix == "/3001"
        assert file_status == KnowledgeFileStatus.SUCCESS
        return [visible_file, hidden_file]

    monkeypatch.setattr(core_database, "get_async_db_session", lambda: _Session())
    monkeypatch.setattr(svc_mod, "get_async_db_session", lambda: _Session())
    monkeypatch.setattr(svc_mod.SpaceFileDao, "get_children_by_prefix", _children_by_prefix)
    monkeypatch.setattr(service, "_build_child_permission_context", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_filter_visible_child_items", AsyncMock(return_value=[visible_file]))

    result = await service._handle_file_folder_extra_info([folder])

    assert result[0]["success_file_num"] == 2
    assert result[0]["visible_success_file_num"] == 1


@pytest.mark.asyncio
async def test_get_space_folder_stats_returns_counts_in_request_order(monkeypatch):
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, user_name="tester")

    folder_a = _file(3001, folder=True, path="")
    folder_b = _file(3002, folder=True, path="")

    async def _get_files_by_ids(file_ids):
        assert file_ids == [3002, 3001]
        return [folder_a, folder_b]

    monkeypatch.setattr(service, "_require_read_permission", AsyncMock())
    monkeypatch.setattr(service, "_require_resource_permission", AsyncMock())
    monkeypatch.setattr(
        service,
        "_load_folder_stat_counts",
        AsyncMock(
            return_value={
                3001: {
                    "file_num": 7,
                    "success_file_num": 5,
                    "visible_success_file_num": 4,
                    "processing_file_num": 1,
                },
                3002: {
                    "file_num": 3,
                    "success_file_num": 2,
                    "visible_success_file_num": 2,
                    "processing_file_num": 0,
                },
            }
        ),
    )
    monkeypatch.setattr(svc_mod.KnowledgeFileDao, "aget_file_by_ids", staticmethod(_get_files_by_ids))

    result = await service.get_space_folder_stats(7101, [3002, 3001, 3002])

    assert result == {
        "stats": [
            {
                "folder_id": 3002,
                "file_num": 3,
                "success_file_num": 2,
                "visible_success_file_num": 2,
                "processing_file_num": 0,
            },
            {
                "folder_id": 3001,
                "file_num": 7,
                "success_file_num": 5,
                "visible_success_file_num": 4,
                "processing_file_num": 1,
            },
        ]
    }
    service._require_read_permission.assert_awaited_once_with(7101)
    service._require_resource_permission.assert_any_await("can_read", "folder", 3001)
    service._require_resource_permission.assert_any_await("can_read", "folder", 3002)


@pytest.mark.asyncio
async def test_get_space_folder_stats_applies_filters(monkeypatch):
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, user_name="tester")

    space = SimpleNamespace(id=7101, index_name="idx")
    folder = _file(3001, folder=True, path="")

    async def _get_files_by_ids(file_ids):
        assert file_ids == [3001]
        return [folder]

    monkeypatch.setattr(service, "_require_read_permission", AsyncMock(return_value=space))
    monkeypatch.setattr(service, "_require_resource_permission", AsyncMock())
    monkeypatch.setattr(
        service,
        "_load_filtered_folder_stat_counts",
        AsyncMock(
            return_value={
                3001: {
                    "file_num": 2,
                    "success_file_num": 1,
                    "visible_success_file_num": 1,
                    "processing_file_num": 1,
                },
            }
        ),
    )
    monkeypatch.setattr(service, "_load_folder_stat_counts", AsyncMock())
    monkeypatch.setattr(svc_mod.KnowledgeFileDao, "aget_file_by_ids", staticmethod(_get_files_by_ids))

    result = await service.get_space_folder_stats(
        7101,
        [3001],
        file_status=[KnowledgeFileStatus.SUCCESS.value, KnowledgeFileStatus.WAITING.value],
        keyword="制度",
        tag_ids=[11],
    )

    assert result == {
        "stats": [
            {
                "folder_id": 3001,
                "file_num": 2,
                "success_file_num": 1,
                "visible_success_file_num": 1,
                "processing_file_num": 1,
            },
        ]
    }
    service._load_filtered_folder_stat_counts.assert_awaited_once_with(
        space=space,
        folders=[folder],
        file_status=[KnowledgeFileStatus.SUCCESS.value, KnowledgeFileStatus.WAITING.value],
        keyword="制度",
        tag_ids=[11],
    )
    service._load_folder_stat_counts.assert_not_called()


@pytest.mark.asyncio
async def test_load_filtered_folder_stat_counts_aggregates_descendant_files(monkeypatch):
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    service.version_repo = None
    space = SimpleNamespace(id=7101, index_name="idx")
    folder = _file(3001, folder=True, path="")
    visible_success = _file(9001, path="/3001")
    waiting = _file(9002, path="/3001/sub", status=KnowledgeFileStatus.WAITING.value)
    outside = _file(9003, path="", status=KnowledgeFileStatus.SUCCESS.value)
    captured = {}

    async def _aget_file_by_filters(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return [visible_success, waiting, outside]

    monkeypatch.setattr(service, "_resolve_folder_stats_tag_file_ids", AsyncMock(return_value=[9001, 9002]))
    monkeypatch.setattr(service, "_resolve_folder_stats_keyword_file_ids", AsyncMock(return_value=[9001]))
    monkeypatch.setattr(service, "_build_child_permission_context", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_filter_visible_child_items", AsyncMock(return_value=[visible_success]))
    monkeypatch.setattr(svc_mod.KnowledgeFileDao, "aget_file_by_filters", staticmethod(_aget_file_by_filters))

    result = await service._load_filtered_folder_stat_counts(
        space=space,
        folders=[folder],
        file_status=[KnowledgeFileStatus.SUCCESS.value, KnowledgeFileStatus.WAITING.value],
        keyword="制度",
        tag_ids=[11],
    )

    assert result[3001] == {
        "file_num": 2,
        "success_file_num": 1,
        "visible_success_file_num": 1,
        "processing_file_num": 1,
    }
    assert captured["args"][0] == 7101
    assert captured["kwargs"]["file_name"] == "制度"
    assert captured["kwargs"]["status"] == [
        KnowledgeFileStatus.SUCCESS.value,
        KnowledgeFileStatus.WAITING.value,
    ]
    assert captured["kwargs"]["file_ids"] == [9001, 9002]
    assert captured["kwargs"]["extra_file_ids"] == [9001]
    assert captured["kwargs"]["file_type"] == FileType.FILE.value


@pytest.mark.asyncio
async def test_handle_file_folder_extra_info_exposes_business_domain_code_before_encoding(monkeypatch):
    import json

    service = object.__new__(svc_mod.KnowledgeSpaceService)
    file_item = _file(4001)
    file_item.split_rule = json.dumps({"business_domain_code": "EM"})
    file_item.file_encoding = None
    file_item.abstract = "summary"
    file_item.thumbnails = None
    file_item.similar_status = 0

    monkeypatch.setattr(
        svc_mod.KnowledgeSpaceService,
        "_load_document_distribution_info",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        svc_mod.KnowledgeSpaceService,
        "_load_file_tags_batch",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        svc_mod.KnowledgeSpaceService,
        "get_logo_share_link",
        staticmethod(lambda value: value),
    )

    result = await service._handle_file_folder_extra_info([file_item])

    assert result[0]["business_domain_code"] == "EM"
    assert result[0]["file_encoding"] is None


@pytest.mark.asyncio
async def test_handle_file_folder_extra_info_can_skip_folder_counts():
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    folder = _file(3001, folder=True, path="")

    result = await service._handle_file_folder_extra_info([folder], include_folder_counts=False)

    assert result[0]["summary"] == ""
    assert "file_num" not in result[0]
    assert "success_file_num" not in result[0]
    assert "visible_success_file_num" not in result[0]
    assert "processing_file_num" not in result[0]


@pytest.mark.asyncio
async def test_handle_file_folder_extra_info_uses_folder_count_override():
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    folder = _file(3001, folder=True, path="")

    result = await service._handle_file_folder_extra_info(
        [folder],
        folder_counts_override={
            3001: {
                "file_num": 2,
                "success_file_num": 1,
                "visible_success_file_num": 1,
                "processing_file_num": 1,
            },
        },
    )

    assert result[0]["file_num"] == 2
    assert result[0]["success_file_num"] == 1
    assert result[0]["visible_success_file_num"] == 1
    assert result[0]["processing_file_num"] == 1
