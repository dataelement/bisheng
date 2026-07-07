"""改动③：list_space_children 的 enrich_files 参数。

签名测试用 AST 避免重依赖导入（参照 test_list_children_endpoint.py）；
行为测试直接调 _handle_file_folder_extra_info，mock DB 依赖。
"""
import ast
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

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
    svc.get_logo_share_link = Mock(return_value="thumb")
    return svc


def _make_file(file_id: int):
    f = Mock()
    f.file_type = FileType.FILE
    f.id = file_id
    f.thumbnails = ""
    f.abstract = "摘要"
    f.similar_status = 0
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
    result = await svc._handle_file_folder_extra_info(
        [_make_file(9001)], include_folder_counts=True, enrich_files=True
    )
    assert result[0]["tags"] == [{"tag_name": "x"}]
    assert "version_no" in result[0]
    svc._load_file_tags_batch.assert_awaited()
