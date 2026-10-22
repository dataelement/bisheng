import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids
from test.mcp_server.test_mcp_server import server, session


@pytest.mark.parametrize(
    "tool,args",
    [
        ("list_knowledge", {"external_id": "forbidden"}),
        ("list_folders", {"knowledge_id": 1, "folder_id": True}),
        ("list_files", {"knowledge_id": "1", "folder_id": "305"}),
        ("search_files", {"keyword": "q", "folder_scope": {"knowledge_id": 1, "folder_id": None}}),
        ("list_files", {"knowledge_id": 1, "sort_by": "object_name"}),
        ("search_files", {"keyword": "q", "knowledge_ids": [1], "folder_scope": {"knowledge_id": 2, "folder_id": 3}}),
        ("get_file_detail", {"knowledge_id": 1, "file_id": 2, "tenant_id": 99}),
        ("upload_file", {"knowledge_id": 1, "file_name": "../a.txt", "content_base64": "YQ=="}),
        ("create_document", {"knowledge_id": 1, "file_name": "a.txt", "content": "x", "content_format": "markdown"}),
        ("retrieve_chunks", {"query": "q", "knowledge_base_ids": [1], "filters": {"external_id": "forbidden"}}),
        (
            "retrieve_chunks",
            {
                "query": "q",
                "knowledge_base_ids": [1],
                "filters": {
                    "knowledge_base_filters": [{"knowledge_base_id": 1, "tenant_id": 99}],
                },
            },
        ),
    ],
)
async def test_new_tool_invalid_arguments_never_open_services(monkeypatch, tool, args):
    """AC-13, AC-17: new inputs reject identity, traversal and inconsistent scope."""
    async with server(monkeypatch) as (app, _, _):
        runtime = app.routes[0].endpoint
        factory = AsyncMock(side_effect=AssertionError("business must not open"))
        runtime.tool_runtime.factory = factory
        async with session(app) as client:
            result = await client.call_tool(tool, args)
            assert result.isError
        factory.assert_not_called()


async def test_new_tool_schemas_and_annotations(monkeypatch):
    """AC-02, AC-17: every new tool is strict and writes are described accurately."""
    async with server(monkeypatch) as (app, _, _):
        async with session(app) as client:
            tools = (await client.list_tools()).tools
            for tool in tools:
                assert tool.inputSchema["additionalProperties"] is False
                assert not {"user_id", "tenant_id", "external_id", "file_path"} & tool.inputSchema["properties"].keys()
                assert tool.outputSchema
                assert tool.annotations.readOnlyHint == (tool.name not in {"create_document", "upload_file"})
            by_name = {tool.name: tool for tool in tools}
            assert by_name["upload_file"].inputSchema["properties"]["content_base64"]["maxLength"] == 69905068
            assert by_name["create_document"].inputSchema["properties"]["content"]["maxLength"] == 10 * 1024 * 1024
            for name, field, key, limit in [
                ("search_files", "knowledge_ids", "maxItems", 20),
                ("list_files", "statuses", "maxItems", 7),
                ("upload_file", "manual_tag_ids", "maxItems", 100),
                ("create_document", "file_category_code", "maxLength", 16),
            ]:
                choices = by_name[name].inputSchema["properties"][field]["anyOf"]
                assert next(choice for choice in choices if choice["type"] != "null")[key] == limit
            for name in ("list_folders", "list_files", "create_document", "upload_file"):
                choices = by_name[name].inputSchema["properties"]["folder_id"]["anyOf"]
                assert {choice["type"] for choice in choices} == {"integer", "string", "null"}
            scope = by_name["search_files"].inputSchema["$defs"]["FolderScope"]
            assert {choice["type"] for choice in scope["properties"]["folder_id"]["anyOf"]} == {"integer", "string"}
        assert app.routes[0].endpoint.max_body_bytes == 80 * 1024 * 1024


@pytest.mark.parametrize("folder_id", [305, "305", "000305", None])
async def test_folder_id_is_normalized_before_all_tool_services(monkeypatch, folder_id):
    """AC-FOLDER-ID: SDK accepts both ID representations and preserves root semantics."""
    seen = []

    async def operation(**params):
        seen.append(params)
        if "file_name" in params:
            return {
                "file_id": 9,
                "knowledge_id": 1,
                "folder_id": params["folder_id"],
                "file_name": params["file_name"],
                "status": 5,
                "accepted": True,
                "content_ready": False,
            }
        return {"data": [], "page_size": 20, "has_more": False, "next_cursor": None}

    @asynccontextmanager
    async def factory(request, user):
        yield SimpleNamespace(
            **dict.fromkeys(("list_folders", "list_files", "search_files", "create_document", "upload_file"), operation)
        )

    async with server(monkeypatch) as (app, _, _):
        app.routes[0].endpoint.tool_runtime.factory = factory
        async with session(app) as client:
            requests = [
                ("list_folders", {"knowledge_id": 1, "folder_id": folder_id}),
                ("list_files", {"knowledge_id": 1, "folder_id": folder_id}),
                ("create_document", {"knowledge_id": 1, "folder_id": folder_id, "file_name": "a.md", "content": "x"}),
                (
                    "upload_file",
                    {"knowledge_id": 1, "folder_id": folder_id, "file_name": "a.txt", "content_base64": "YQ=="},
                ),
            ]
            if folder_id is not None:
                requests.append(
                    (
                        "search_files",
                        {
                            "keyword": "q",
                            "knowledge_ids": [1],
                            "folder_scope": {"knowledge_id": 1, "folder_id": folder_id},
                        },
                    )
                )
            else:
                requests[0][1].pop("folder_id")
            for name, args in requests:
                result = await client.call_tool(name, args)
                assert not result.isError, (name, result)
                params = seen[-1]
                actual = params["folder_scope"]["folder_id"] if name == "search_files" else params["folder_id"]
                assert actual == (None if folder_id is None else 305)
                assert actual is None or type(actual) is int
            assert len(seen) == len(requests)


@pytest.mark.parametrize(
    "folder_id",
    ["", "abc", "0", "-1", "+305", "305.0", "3e2", " 305 ", "305\n", "\uff13\uff10\uff15", 0, -1, 1.5, True],
)
async def test_invalid_folder_id_never_opens_business_services(monkeypatch, folder_id):
    """AC-FOLDER-ID: invalid IDs cannot silently select root or coerce another folder."""
    async with server(monkeypatch) as (app, _, _):
        factory = AsyncMock(side_effect=AssertionError("business must not open"))
        app.routes[0].endpoint.tool_runtime.factory = factory
        async with session(app) as client:
            result = await client.call_tool("list_files", {"knowledge_id": 1, "folder_id": folder_id})
            assert result.isError
        factory.assert_not_called()


@pytest.mark.parametrize("declared", [False, True])
async def test_body_limit_runs_before_sdk_or_business(monkeypatch, declared):
    """AC-13: real receive bytes are bounded, even without Content-Length."""
    async with server(monkeypatch) as (app, calls, _):
        runtime = app.routes[0].endpoint
        monkeypatch.setattr(runtime, "max_body_bytes", 64)

        async def body():
            yield b" " * 40
            yield b" " * 40

        headers = {"X-Developer-Token": "first", "Content-Type": "application/json"}
        if declared:
            headers["Content-Length"] = "80"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            response = await client.post("http://localhost/mcp", content=body(), headers=headers)
        assert response.status_code == 413
        assert not calls


async def test_new_tool_tasks_isolate_tenants_and_sanitize_failures(monkeypatch, caplog):
    """AC-16, AC-17: real SDK tasks restore identity and do not expose downstream text."""
    active = set()

    @asynccontextmanager
    async def factory(request, user):
        active.add(user.user_id)

        async def list_knowledge(**kwargs):
            await asyncio.sleep(0.01)
            assert get_current_tenant_id() == user.tenant_id
            assert get_visible_tenant_ids() == frozenset({user.tenant_id})
            if kwargs.get("name") == "failure":
                raise RuntimeError("sensitive-connection-password")
            return {"data": [{"id": user.user_id}], "page_size": 20, "has_more": False, "next_cursor": None}

        try:
            yield SimpleNamespace(list_knowledge=list_knowledge)
        finally:
            active.remove(user.user_id)

    async with server(monkeypatch) as (app, _, _):
        app.routes[0].endpoint.tool_runtime.factory = factory

        async def invoke(token):
            async with session(app, token=token) as client:
                return await client.call_tool("list_knowledge", {})

        first, second = await asyncio.gather(invoke("first"), invoke("second"))
        assert first.structuredContent["data"] == [{"id": 7}]
        assert second.structuredContent["data"] == [{"id": 8}]
        async with session(app) as client:
            error = await client.call_tool("list_knowledge", {"name": "failure"})
            assert error.isError and "sensitive-connection" not in str(error)
    assert not active and "sensitive-connection-password" not in caplog.text
