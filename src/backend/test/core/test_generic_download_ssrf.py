"""Offline SSRF regressions: never contact advisory destinations."""

import ast
import ipaddress
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from bisheng.core.cache import utils
from bisheng.knowledge.domain.services.web_link_import_service import KnowledgeWebLinkImportService


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.100.100.200",
        "240.0.0.1",
        "fc00::1",
        "::ffff:127.0.0.1",
    ],
)
async def test_generic_download_rejects_nonpublic_before_network(monkeypatch, address):
    minio = SimpleNamespace(get_minio_share_host=lambda: "https://storage.example")
    monkeypatch.setattr(utils, "get_minio_storage_sync", lambda: minio)
    monkeypatch.setattr(utils, "get_minio_storage", AsyncMock(return_value=minio))

    # Before the fix these sentinels prove that an unsafe transport is reached.
    def unsafe(*args, **kwargs):
        pytest.fail("unvalidated network request")

    monkeypatch.setattr(utils, "requests", SimpleNamespace(get=unsafe), raising=False)
    monkeypatch.setattr(utils, "get_http_client", AsyncMock(return_value=SimpleNamespace(get=unsafe)), raising=False)
    host = f"[{address}]" if ":" in address else address
    with pytest.raises(ValueError):
        utils.file_download(f"http://{host}/canary.txt")
    with pytest.raises(ValueError):
        await utils.async_file_download(f"http://{host}/canary.txt")


@pytest.mark.parametrize(
    "address", ["10.0.0.1", "172.16.0.1", "192.168.0.1", "100.100.100.200", "240.0.0.1", "fc00::1", "::ffff:127.0.0.1"]
)
def test_web_link_blocks_nonpublic(address):
    assert KnowledgeWebLinkImportService._is_blocked_ip(ipaddress.ip_address(address))


def _upload_handler(**namespace):
    # Execute the actual handler without importing the unrelated endpoint graph.
    source = Path("bisheng/open_endpoints/api/endpoints/filelib.py").read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.AsyncFunctionDef) and n.name == "upload_file")
    node.decorator_list = []
    for arg in node.args.args + node.args.kwonlyargs:
        arg.annotation = None
    node.args.defaults = [ast.Constant(None) for _ in node.args.defaults]
    node.args.kw_defaults = [ast.Constant(None) for _ in node.args.kw_defaults]
    node.returns = None
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), "filelib.py", "exec"), namespace)
    return namespace["upload_file"]


@pytest.mark.parametrize("failure", ["identity", "missing", "permission", "unsupported"])
async def test_upload_authorizes_before_fetch(failure):
    denied = HTTPException(403, "denied")
    download = AsyncMock(side_effect=AssertionError("download before authorization"))
    identity = AsyncMock(side_effect=denied if failure == "identity" else None, return_value=SimpleNamespace(user_id=7))
    row = None if failure == "missing" else SimpleNamespace(id=1, type=99 if failure == "unsupported" else 0)
    handler = _upload_handler(
        HTTPException=HTTPException,
        get_open_api_operator_async=identity,
        KnowledgeDao=SimpleNamespace(aquery_by_id=AsyncMock(return_value=row)),
        KnowledgeService=SimpleNamespace(ajudge_knowledge_access=AsyncMock(side_effect=denied)),
        KnowledgeTypeEnum=SimpleNamespace(SPACE=SimpleNamespace(value=3)),
        _KB_TYPES=(0, 1),
        NotFoundError=SimpleNamespace(http_exception=lambda: HTTPException(404)),
        KnowledgeTypeNotSupportedError=SimpleNamespace(http_exception=lambda: HTTPException(400)),
        async_file_download=download,
    )
    with pytest.raises(HTTPException):
        await handler(request=None, knowledge_id=1, file_url="http://169.254.169.254/canary")
    download.assert_not_awaited()


@pytest.mark.parametrize("parent_id", [None, 42])
@pytest.mark.parametrize("uploaded", [False, True])
async def test_space_permission_denial_precedes_fetch_and_upload_write(parent_id, uploaded):
    denied = HTTPException(403, "denied")
    download = AsyncMock(side_effect=AssertionError("download before authorization"))
    save = Mock(side_effect=AssertionError("cache write before authorization"))
    space = SimpleNamespace(_get_folder_for_action=AsyncMock(), _require_action=AsyncMock(side_effect=denied))
    handler = _upload_handler(
        HTTPException=HTTPException,
        get_open_api_operator_async=AsyncMock(return_value=SimpleNamespace(user_id=7)),
        KnowledgeDao=SimpleNamespace(aquery_by_id=AsyncMock(return_value=SimpleNamespace(id=1, type=3))),
        KnowledgeTypeEnum=SimpleNamespace(SPACE=SimpleNamespace(value=3)),
        _build_space_service=lambda *args: space,
        _KB_TYPES=(0, 1),
        async_file_download=download,
        save_download_file=save,
    )
    with pytest.raises(HTTPException):
        await handler(
            request=None,
            knowledge_id=1,
            parent_id=parent_id,
            file=SimpleNamespace(filename="a.txt") if uploaded else None,
            file_url="http://169.254.169.254/canary",
        )
    download.assert_not_awaited()
    save.assert_not_called()
    assert space._require_action.await_args.args == (
        "folder" if parent_id else "knowledge_space",
        parent_id or 1,
        "upload_file",
    )
    if parent_id:
        space._get_folder_for_action.assert_awaited_once_with(1, parent_id)


async def test_space_success_authorizes_before_fetch():
    events = []

    async def permission(*args):
        events.append("authorize")

    async def download(*args):
        events.append("download")
        return "/tmp/cached", "a.txt"

    space = SimpleNamespace(_require_action=permission, add_file=AsyncMock(return_value=["stored"]))
    handler = _upload_handler(
        get_open_api_operator_async=AsyncMock(return_value=SimpleNamespace(user_id=7)),
        KnowledgeDao=SimpleNamespace(aquery_by_id=AsyncMock(return_value=SimpleNamespace(id=1, type=3))),
        KnowledgeTypeEnum=SimpleNamespace(SPACE=SimpleNamespace(value=3)),
        _build_space_service=lambda *args: space,
        _KB_TYPES=(0, 1),
        async_file_download=download,
        resp_200=lambda **kwargs: kwargs,
    )
    assert await handler(request=None, knowledge_id=1, file_url="https://public.example/a") == {"data": "stored"}
    assert events == ["authorize", "download"]
