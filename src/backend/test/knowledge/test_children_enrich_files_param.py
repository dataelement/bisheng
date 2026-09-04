"""改动③：list_space_children 的 enrich_files 参数。

签名测试用 AST 避免重依赖导入（参照 test_list_children_endpoint.py）；
行为测试直接调 _handle_file_folder_extra_info，mock DB 依赖。
"""

import ast
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeState
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "bisheng"


def _find_fn(source: str, name: str):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def test_service_list_space_children_accepts_enrich_files():
    svc_file = _BACKEND_ROOT / "knowledge" / "domain" / "services" / "knowledge_space_service.py"
    fn = _find_fn(svc_file.read_text(), "list_space_children")
    arg_names = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    assert "enrich_files" in arg_names, arg_names


def test_endpoint_children_accepts_enrich_files_query():
    ep_file = _BACKEND_ROOT / "knowledge" / "api" / "endpoints" / "knowledge_space.py"
    for node in ast.walk(ast.parse(ep_file.read_text())):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arg_names = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
        if "enrich_files" not in arg_names:
            continue
        for dec in node.decorator_list:
            if "/children" in ast.unparse(dec):
                return
    raise AssertionError("no /children endpoint with enrich_files kwarg")


def _make_svc():
    svc = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    svc._load_folder_stat_counts = AsyncMock(return_value={})
    svc._load_file_tags_batch = AsyncMock(return_value={9001: [{"tag_name": "x"}]})
    svc.doc_repo = None
    svc.version_repo = None
    svc._entry_permission_ids_by_file = {9001: set()}
    svc.get_logo_share_link = Mock(return_value="thumb")
    return svc


def _make_file(file_id: int):
    f = Mock()
    f.file_type = FileType.FILE
    f.id = file_id
    f.thumbnails = ""
    f.abstract = "摘要"
    f.similar_status = 0
    f.reference_document_id = None
    f.entry_type = None
    f.original_uploader_id = None
    f.original_knowledge_id = None
    f.allow_download = False
    f.knowledge_id = 10
    f.model_dump.return_value = {"id": file_id, "file_name": "a.pdf", "file_type": FileType.FILE.value}
    return f


@pytest.mark.asyncio
async def test_extra_info_skips_file_enrichment_when_disabled():
    svc = _make_svc()
    result = await svc._handle_file_folder_extra_info(
        [_make_file(9001)], include_folder_counts=True, enrich_files=False
    )
    assert "tags" not in result[0]
    assert "version_no" not in result[0]
    assert "thumbnails" not in result[0]
    svc._load_file_tags_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_extra_info_enriches_files_by_default():
    svc = _make_svc()
    result = await svc._handle_file_folder_extra_info([_make_file(9001)], include_folder_counts=True, enrich_files=True)
    assert result[0]["tags"] == [{"tag_name": "x"}]
    assert "version_no" in result[0]
    svc._load_file_tags_batch.assert_awaited()


@pytest.mark.asyncio
async def test_portal_recommendation_display_snapshot_skips_effective_permission_lookup_for_batch():
    svc = _make_svc()
    svc._entry_permission_ids_by_file = {}
    svc._portal_file_download_map = {}
    svc._get_effective_permission_ids = AsyncMock(
        return_value={"view_file", "download_file", "rename_file", "delete_file"}
    )
    files = [_make_file(9001 + offset) for offset in range(20)]

    for file in files:
        assert svc._try_fast_allow_portal_enabled_recommendation(
            file,
            space_id=10,
            portal_enabled_space_ids={10},
        ) is True
    result = await svc._load_document_distribution_info(files)

    svc._get_effective_permission_ids.assert_not_awaited()
    assert svc._portal_file_download_map == {int(file.id): False for file in files}
    expected_capabilities = {
        "can_view": True,
        "can_preview": True,
        "can_download": False,
        "can_move": False,
        "can_manage_members": False,
        "can_edit_content": False,
        "can_publish": False,
        "can_share": False,
        "can_delete": False,
    }
    assert len(result) == 20
    assert all(item["capabilities"] == expected_capabilities for item in result.values())


@pytest.mark.asyncio
async def test_logical_entry_reuses_current_primary_tags_without_leaking_source_id():
    svc = _make_svc()
    logical = _make_file(9001)
    svc._load_document_distribution_info = AsyncMock(
        return_value={
            9001: {
                "_tag_source_file_id": 100,
                "entry_type": "share",
            }
        }
    )
    svc._load_file_tags_batch = AsyncMock(return_value={100: [{"tag_name": "canonical"}]})

    result = await svc._handle_file_folder_extra_info(
        [logical],
        include_folder_counts=True,
        enrich_files=True,
    )

    svc._load_file_tags_batch.assert_awaited_once_with([100])
    assert result[0]["tags"] == [{"tag_name": "canonical"}]
    assert "_tag_source_file_id" not in result[0]


@pytest.mark.asyncio
async def test_logical_entry_reuses_current_primary_file_size_and_version():
    svc = _make_svc()
    logical = _make_file(9001)
    logical.reference_document_id = 501
    logical.entry_type = "share"
    logical.file_size = 0
    logical.allow_download = False
    logical.entry_status = "active"
    logical.desired_content_generation = 1
    logical.applied_content_generation = 1
    logical.desired_entry_generation = 1
    logical.applied_entry_generation = 1
    logical.projection_status = "ready"
    svc._entry_permission_ids_by_file = {9001: {"view_file"}}
    svc.doc_repo = SimpleNamespace(
        find_by_ids=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=501,
                    knowledge_id=10,
                    primary_version_id=601,
                )
            ]
        )
    )
    svc.version_repo = SimpleNamespace(
        find_by_ids=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=601,
                    document_id=501,
                    knowledge_file_id=7001,
                    version_no=3,
                )
            ]
        )
    )
    primary_file = SimpleNamespace(id=7001, file_size=2048)

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids",
        new_callable=AsyncMock,
        return_value=[primary_file],
    ) as load_files:
        result = await svc._load_document_distribution_info([logical])

    assert result[9001]["file_size"] == 2048
    assert result[9001]["version_no"] == 3
    load_files.assert_awaited_once_with([7001])


@pytest.mark.asyncio
async def test_distribution_origin_names_are_loaded_in_batches():
    svc = _make_svc()
    logical = _make_file(9001)
    logical.reference_document_id = 501
    logical.entry_type = "share"
    logical.entry_status = "active"
    logical.original_uploader_id = 42
    logical.original_knowledge_id = 10
    logical.desired_content_generation = 1
    logical.applied_content_generation = 1
    logical.desired_entry_generation = 1
    logical.applied_entry_generation = 1
    logical.projection_status = "ready"
    svc._entry_permission_ids_by_file = {9001: {"view_file"}}

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.UserDao.aget_user_by_ids",
            new_callable=AsyncMock,
            return_value=[SimpleNamespace(user_id=42, user_name="原始上传人")],
        ) as load_users,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids",
            new_callable=AsyncMock,
            return_value=[SimpleNamespace(id=10, name="原始知识库")],
        ) as load_spaces,
    ):
        result = await svc._load_document_distribution_info([logical])

    assert result[9001]["original_uploader_id"] == 42
    assert result[9001]["original_uploader_name"] == "原始上传人"
    assert result[9001]["original_knowledge_id"] == 10
    assert result[9001]["original_knowledge_name"] == "原始知识库"
    load_users.assert_awaited_once_with([42])
    load_spaces.assert_awaited_once_with([10])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("manager_space_state", "expected_reason"),
    [
        (KnowledgeState.PUBLISHED.value, "manager_file_deleted"),
        (KnowledgeState.DELETING.value, "manager_space_deleted"),
    ],
)
async def test_invalid_distribution_reason_is_derived_from_manager_space_in_batch(
    manager_space_state: str,
    expected_reason: str,
):
    svc = _make_svc()
    logical = _make_file(9001)
    logical.reference_document_id = 501
    logical.entry_type = "publish"
    logical.entry_status = "invalid"
    logical.desired_content_generation = 1
    logical.applied_content_generation = 1
    logical.desired_entry_generation = 2
    logical.applied_entry_generation = 1
    logical.projection_status = "pending"
    svc._entry_permission_ids_by_file = {9001: {"delete_file"}}
    svc.doc_repo = SimpleNamespace(
        find_by_ids=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=501,
                    knowledge_id=10,
                    primary_version_id=None,
                    lifecycle_status="deleting",
                )
            ]
        )
    )

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service."
        "KnowledgeDao.async_get_spaces_by_ids",
        new_callable=AsyncMock,
        return_value=[
            SimpleNamespace(id=10, name="管理知识库", state=manager_space_state)
        ],
    ) as load_spaces:
        result = await svc._load_document_distribution_info([logical])

    assert result[9001]["distribution_invalid_reason"] == expected_reason
    assert result[9001]["capabilities"] == {
        "can_view": False,
        "can_preview": False,
        "can_download": False,
        "can_move": False,
        "can_manage_members": False,
        "can_edit_content": False,
        "can_publish": False,
        "can_share": False,
        "can_delete": True,
    }
    load_spaces.assert_awaited_once_with([10])


@pytest.mark.asyncio
async def test_normal_file_original_uploader_name_is_loaded():
    svc = _make_svc()
    normal_file = _make_file(9002)
    normal_file.entry_type = None
    normal_file.original_uploader_id = 42
    normal_file.user_id = 7
    normal_file.user_name = "token-user"
    svc._entry_permission_ids_by_file = {9002: {"view_file"}}

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.UserDao.aget_user_by_ids",
        new_callable=AsyncMock,
        return_value=[SimpleNamespace(user_id=42, user_name="原始上传人")],
    ) as load_users:
        result = await svc._load_document_distribution_info([normal_file])

    assert result[9002]["original_uploader_id"] == 42
    assert result[9002]["original_uploader_name"] == "原始上传人"
    assert "original_knowledge_id" not in result[9002]
    load_users.assert_awaited_once_with([42])


@pytest.mark.asyncio
async def test_share_entry_enrichment_keeps_target_folder_and_adds_direct_source_metadata():
    svc = _make_svc()
    logical = _make_file(9001)
    logical.entry_type = "share"
    logical.share_source_file_id = 7001
    logical.model_dump.return_value = {
        "id": 9001,
        "knowledge_id": 20,
        "file_name": "制度.pdf",
        "file_type": FileType.FILE.value,
        "file_level_path": "/900",
        "entry_type": "share",
        "share_source_file_id": 7001,
    }
    svc._resolve_shougang_portal_source_metadata = AsyncMock(
        return_value={
            9001: {
                "source_space_id": 10,
                "source_space_name": "来源知识库",
                "source_department_name": "来源部门",
                "source_folder_path": "来源知识库/源目录",
                "source_path": "来源知识库>源目录/制度.pdf",
            }
        }
    )

    result = await svc._handle_file_folder_extra_info([logical])

    assert result[0]["file_level_path"] == "/900"
    assert result[0]["source_space_id"] == 10
    assert result[0]["source_space_name"] == "来源知识库"
    assert result[0]["source_department_name"] == "来源部门"
    assert result[0]["source_path"] == "来源知识库>源目录/制度.pdf"


@pytest.mark.asyncio
async def test_share_source_metadata_resolves_share_source_entry_instead_of_receiver_or_manager():
    svc = _make_svc()
    svc.version_repo = SimpleNamespace(
        find_primary_versions_by_file_ids=AsyncMock(
            side_effect=AssertionError("share source must not fall back to canonical manager")
        )
    )
    svc.doc_repo = SimpleNamespace(
        find_by_ids=AsyncMock(side_effect=AssertionError("share source must not fall back to canonical manager"))
    )
    source_file = SimpleNamespace(
        id=7001,
        knowledge_id=10,
        file_name="制度.pdf",
        file_level_path="/701",
        file_type=FileType.FILE.value,
    )
    source_folder = SimpleNamespace(
        id=701,
        knowledge_id=10,
        file_name="源目录",
        file_level_path="",
        file_type=FileType.DIR.value,
    )

    async def fake_get_files(file_ids):
        ids = {int(file_id) for file_id in file_ids}
        if 7001 in ids:
            return [source_file]
        return [source_folder] if 701 in ids else []

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids",
            new_callable=AsyncMock,
            side_effect=fake_get_files,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_space_source_metadata_by_ids",
            new_callable=AsyncMock,
            return_value={10: ("来源知识库", "来源部门", "来源", "来源")},
        ),
    ):
        result = await svc._resolve_shougang_portal_source_metadata(
            [
                {
                    "id": 9001,
                    "knowledge_id": 20,
                    "file_name": "制度.pdf",
                    "file_level_path": "/900",
                    "entry_type": "share",
                    "share_source_file_id": 7001,
                }
            ]
        )

    assert result == {
        9001: {
            "source_space_id": 10,
            "source_space_name": "来源知识库",
            "source_department_name": "来源部门",
            "source_department_short_name": "来源",
            "source_department_display_name": "来源",
            "source_folder_path": "来源知识库/源目录",
            "source_path": "来源知识库>源目录/制度.pdf",
        }
    }


@pytest.mark.asyncio
async def test_source_space_metadata_query_returns_department_name_without_extra_lookup():
    session = SimpleNamespace(
        exec=AsyncMock(
            return_value=SimpleNamespace(
                all=lambda: [
                    (10, "来源知识库", "来源部门", "来源"),
                    (11, "无绑定知识库", None, None),
                ]
            )
        )
    )

    @asynccontextmanager
    async def fake_session():
        yield session

    with patch(
        "bisheng.knowledge.domain.models.knowledge.get_async_db_session",
        new=fake_session,
    ):
        result = await KnowledgeDao.async_get_space_source_metadata_by_ids([10, 11])

    assert result == {
        10: ("来源知识库", "来源部门", "来源", "来源"),
        11: ("无绑定知识库", "", None, ""),
    }
    session.exec.assert_awaited_once()


def test_children_page_keeps_file_tags_on_response_schema():
    """list_space_children wraps extra_info dicts in KnowledgeSpaceFileResponse.

    tags must be a declared field, otherwise Pydantic strips them and the
    file list always shows '--' even when TagLink rows already exist.
    """
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceChildrenPage

    page = KnowledgeSpaceChildrenPage(
        data=[
            {
                "id": 9992193,
                "knowledge_id": 40,
                "file_name": "建筑工程施工安全操作规程》（DB11T1833-2021）.pdf",
                "tags": [
                    {"id": 101, "name": "安全生产规程", "resource_type": "system_tag"},
                    {"id": 102, "name": "岗位操作规程", "resource_type": "system_tag"},
                ],
            }
        ],
        page_size=20,
        has_more=False,
    )

    assert [item.name for item in page.data[0].tags] == ["安全生产规程", "岗位操作规程"]
    dumped = page.model_dump()
    assert dumped["data"][0]["tags"][0]["name"] == "安全生产规程"
