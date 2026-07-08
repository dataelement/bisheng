"""改动:list_space_children 的 folder_count_mode(shallow 轻量直接计数 + 显式 has_children)。

签名测试用 AST(参照 test_children_enrich_files_param.py);行为测试直接调
_handle_file_folder_extra_info,mock 掉 deep/shallow 两个加载器验证分流与 has_children。
零 OpenFGA 用 AST 断言 _load_folder_direct_counts 源码不引用鉴权辅助函数。
"""
import ast
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "bisheng"
_SVC_FILE = _BACKEND_ROOT / "knowledge" / "domain" / "services" / "knowledge_space_service.py"
_EP_FILE = _BACKEND_ROOT / "knowledge" / "api" / "endpoints" / "knowledge_space.py"


def _find_fn(source: str, name: str):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def test_service_list_space_children_accepts_folder_count_mode():
    fn = _find_fn(_SVC_FILE.read_text(), "list_space_children")
    arg_names = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    assert "folder_count_mode" in arg_names, arg_names


def test_endpoint_children_accepts_folder_count_mode_query():
    for node in ast.walk(ast.parse(_EP_FILE.read_text())):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arg_names = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
        if "folder_count_mode" not in arg_names:
            continue
        for dec in node.decorator_list:
            if "/children" in ast.unparse(dec):
                return
    raise AssertionError("no /children endpoint with folder_count_mode kwarg")


def test_direct_counts_helper_makes_no_permission_calls():
    """轻量计数零 OpenFGA:源码不得引用逐项鉴权/权限上下文辅助。"""
    fn = _find_fn(_SVC_FILE.read_text(), "_load_folder_direct_counts")
    assert fn is not None, "_load_folder_direct_counts 未定义"
    body = ast.unparse(fn)
    assert "_filter_visible_child_items" not in body
    assert "_build_child_permission_context" not in body


def _make_folder(folder_id: int):
    f = Mock()
    f.file_type = FileType.DIR
    f.id = folder_id
    f.knowledge_id = 131
    f.file_level_path = ""
    f.model_dump.return_value = {"id": folder_id, "file_type": FileType.DIR.value, "file_name": "d"}
    return f


@pytest.mark.asyncio
async def test_extra_info_shallow_uses_direct_counts_and_sets_has_children():
    svc = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    svc._load_folder_stat_counts = AsyncMock(return_value={})
    svc._load_folder_direct_counts = AsyncMock(
        return_value={10: {"file_num": 2, "success_file_num": 2,
                           "visible_success_file_num": 2, "processing_file_num": 0,
                           "has_children": True}}
    )
    result = await svc._handle_file_folder_extra_info(
        [_make_folder(10)], include_folder_counts=True,
        enrich_files=False, folder_count_mode="shallow",
    )
    assert result[0]["visible_success_file_num"] == 2
    assert result[0]["has_children"] is True
    svc._load_folder_direct_counts.assert_awaited_once()
    svc._load_folder_stat_counts.assert_not_awaited()


@pytest.mark.asyncio
async def test_extra_info_deep_still_uses_stat_counts():
    svc = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    svc._load_folder_stat_counts = AsyncMock(
        return_value={10: {"file_num": 5, "success_file_num": 5,
                           "visible_success_file_num": 3, "processing_file_num": 0}}
    )
    svc._load_folder_direct_counts = AsyncMock(return_value={})
    result = await svc._handle_file_folder_extra_info(
        [_make_folder(10)], include_folder_counts=True,
        enrich_files=False, folder_count_mode="deep",
    )
    assert result[0]["visible_success_file_num"] == 3
    svc._load_folder_stat_counts.assert_awaited_once()
    svc._load_folder_direct_counts.assert_not_awaited()
