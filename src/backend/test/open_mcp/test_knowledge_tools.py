import inspect
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from bisheng.open_mcp.contracts import (
    KnowledgeCreateInput,
    KnowledgeIdInput,
    KnowledgeListInput,
    KnowledgeRetrieveInput,
    KnowledgeUpdateInput,
)
from bisheng.open_mcp.tools import knowledge as knowledge_tools
from bisheng.open_mcp.tools.knowledge import (
    knowledge_clear,
    knowledge_create,
    knowledge_delete,
    knowledge_list,
    knowledge_retrieve,
    knowledge_update,
)


@asynccontextmanager
async def _repositories():
    yield object(), object()


def _install_repositories(monkeypatch):
    monkeypatch.setattr("bisheng.open_mcp.application.knowledge_repositories", _repositories)


@pytest.mark.asyncio
async def test_knowledge_list_calls_application_facade_and_maps_explicit_output(monkeypatch):
    _install_repositories(monkeypatch)
    facade = AsyncMock(
        return_value={
            "data": [
                {
                    "id": 67,
                    "name": "f067",
                    "type": 0,
                    "auth_type": "public",
                    "is_released": False,
                    "is_shared": False,
                    "auto_tag_enabled": False,
                    "actions": ["read"],
                    "permission_ids": [999],
                }
            ],
            "page_size": 5,
            "has_more": False,
            "next_cursor": None,
        }
    )
    monkeypatch.setattr("bisheng.open_mcp.application.list_knowledge", facade)

    result = await knowledge_list(KnowledgeListInput(type=0, name="f067", page_size=5))

    assert result.data[0].actions == ["read"]
    assert "permission_ids" not in result.data[0].model_dump()
    assert facade.await_args.kwargs["command"].resource_type == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "arguments", "facade_name"),
    [
        (
            knowledge_create,
            KnowledgeCreateInput(name="f067", type=0, model="embedding"),
            "create_knowledge",
        ),
        (
            knowledge_update,
            KnowledgeUpdateInput(knowledge_id=67, name="updated"),
            "update_knowledge",
        ),
    ],
)
async def test_knowledge_write_handlers_return_explicit_resource(monkeypatch, handler, arguments, facade_name):
    _install_repositories(monkeypatch)
    facade = AsyncMock(
        return_value={
            "id": 67,
            "name": "f067",
            "type": 0,
            "auth_type": "public",
            "is_released": False,
            "is_shared": False,
            "auto_tag_enabled": False,
            "actions": ["read"],
        }
    )
    monkeypatch.setattr(f"bisheng.open_mcp.application.{facade_name}", facade)

    result = await handler(arguments)

    assert result.id == 67
    assert result.actions == ["read"]
    facade.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "facade_name"),
    [
        (knowledge_delete, "delete_knowledge"),
        (knowledge_clear, "clear_knowledge"),
    ],
)
async def test_destructive_knowledge_handlers_return_operation_result(monkeypatch, handler, facade_name):
    _install_repositories(monkeypatch)
    facade = AsyncMock()
    monkeypatch.setattr(f"bisheng.open_mcp.application.{facade_name}", facade)

    result = await handler(KnowledgeIdInput(knowledge_id=67))

    assert result.success is True
    assert facade.await_args.kwargs["knowledge_id"] == 67


@pytest.mark.asyncio
async def test_retrieve_handler_maps_business_chunks(monkeypatch):
    _install_repositories(monkeypatch)
    facade = AsyncMock(
        return_value={
            "chunks": [
                {
                    "content": "answer",
                    "knowledge_id": 67,
                    "document_id": 7,
                    "document_name": "f067.txt",
                    "document_update_time": "",
                    "chunk_index": 0,
                }
            ],
            "total": 1,
        }
    )
    monkeypatch.setattr("bisheng.open_mcp.application.retrieve_knowledge", facade)

    result = await knowledge_retrieve(
        KnowledgeRetrieveInput(query="answer", knowledge_base_ids=[67])
    )

    assert result.total == 1
    assert result.chunks[0].document_name == "f067.txt"


def test_mcp_knowledge_tools_do_not_import_http_endpoint_module():
    assert "open_endpoints.api.endpoints" not in inspect.getsource(knowledge_tools)
