import inspect
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bisheng.open_mcp.contracts import (
    KnowledgeFileDeleteInput,
    KnowledgeFileListInput,
    KnowledgeFilesDeleteInput,
    KnowledgeFileUploadInput,
)
from bisheng.open_mcp.tools import file as file_tools
from bisheng.open_mcp.tools.file import (
    knowledge_file_delete,
    knowledge_file_list,
    knowledge_file_upload,
    knowledge_files_delete,
)


@asynccontextmanager
async def _repositories():
    yield object(), object()


def _install_repositories(monkeypatch):
    monkeypatch.setattr("bisheng.open_mcp.application.knowledge_repositories", _repositories)


@pytest.mark.asyncio
async def test_file_list_preserves_structured_tags_and_filters_legacy_fields(monkeypatch):
    _install_repositories(monkeypatch)
    facade = AsyncMock(
        return_value={
            "data": [
                {
                    "id": 7,
                    "knowledge_id": 67,
                    "file_name": "f067.txt",
                    "file_type": 1,
                    "tags": [{"id": 1, "name": "MCP"}],
                    "permission_ids": [999],
                }
            ],
            "page_size": 10,
            "has_more": False,
            "writeable": True,
        }
    )
    monkeypatch.setattr("bisheng.open_mcp.application.list_knowledge_files", facade)

    result = await knowledge_file_list(KnowledgeFileListInput(knowledge_id=67))

    assert result.data[0].tags[0].name == "MCP"
    assert "permission_ids" not in result.data[0].model_dump()
    assert result.writeable is True


@pytest.mark.asyncio
async def test_file_upload_passes_managed_path_to_application_facade(monkeypatch, tmp_path):
    _install_repositories(monkeypatch)
    path = tmp_path / "f067.txt"
    path.write_bytes(b"mcp upload")

    @asynccontextmanager
    async def _prepared(arguments):
        yield str(path), path.name

    facade = AsyncMock(
        return_value={
            "id": 7,
            "knowledge_id": 67,
            "file_name": "f067.txt",
            "file_type": 1,
        }
    )
    preflight = AsyncMock()
    monkeypatch.setattr("bisheng.open_mcp.tools.file.prepared_upload", _prepared)
    monkeypatch.setattr("bisheng.open_mcp.application.ensure_upload_allowed", preflight)
    monkeypatch.setattr("bisheng.open_mcp.application.upload_knowledge_file", facade)

    result = await knowledge_file_upload(
        KnowledgeFileUploadInput(
            knowledge_id=67,
            file_name="f067.txt",
            content_base64="bWNwIHVwbG9hZA==",
        )
    )

    assert result.id == 7
    preflight.assert_awaited_once()
    assert Path(facade.await_args.kwargs["path"]) == path
    assert facade.await_args.kwargs["file_name"] == "f067.txt"


@pytest.mark.asyncio
async def test_file_upload_rejects_target_before_materializing_file(monkeypatch):
    _install_repositories(monkeypatch)
    materialized = False

    @asynccontextmanager
    async def _prepared(arguments):
        nonlocal materialized
        materialized = True
        yield "/unused", "unused.txt"

    preflight = AsyncMock(side_effect=RuntimeError("denied"))
    facade = AsyncMock()
    monkeypatch.setattr("bisheng.open_mcp.tools.file.prepared_upload", _prepared)
    monkeypatch.setattr("bisheng.open_mcp.application.ensure_upload_allowed", preflight)
    monkeypatch.setattr("bisheng.open_mcp.application.upload_knowledge_file", facade)

    with pytest.raises(RuntimeError, match="denied"):
        await knowledge_file_upload(
            KnowledgeFileUploadInput(
                knowledge_id=67,
                file_name="f067.txt",
                content_base64="ZjA2Nw==",
            )
        )

    assert materialized is False
    facade.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "arguments", "expected"),
    [
        (knowledge_file_delete, KnowledgeFileDeleteInput(file_id=7), [7]),
        (knowledge_files_delete, KnowledgeFilesDeleteInput(file_ids=[7, 8]), [7, 8]),
    ],
)
async def test_file_delete_handlers_use_application_facade(monkeypatch, handler, arguments, expected):
    facade = AsyncMock()
    monkeypatch.setattr("bisheng.open_mcp.application.delete_knowledge_files", facade)

    result = await handler(arguments)

    assert result.success is True
    assert facade.await_args.kwargs["file_ids"] == expected


def test_mcp_file_tools_do_not_import_http_endpoint_module():
    assert "open_endpoints.api.endpoints" not in inspect.getsource(file_tools)
