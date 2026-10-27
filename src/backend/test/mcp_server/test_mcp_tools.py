import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from bisheng.common.errcode import BaseErrorCode
from bisheng.core.context.tenant import get_current_tenant_id, get_visible_tenant_ids
from test.mcp_server.test_mcp_server import server, session


async def test_all_tools_require_external_account_before_business(monkeypatch, caplog):
    """F081 AC-01, AC-07: 十工具 schema 及缺参执行一致拒绝。"""
    import logging

    caplog.set_level(logging.INFO)
    resolver = AsyncMock(side_effect=AssertionError("identity must not open"))
    arguments = {
        "list_knowledge": {},
        "list_folders": {"knowledge_id": 1},
        "list_files": {"knowledge_id": 1},
        "search_files": {"keyword": "q"},
        "get_file_detail": {"knowledge_id": 1, "file_id": 2},
        "get_file_source": {"knowledge_id": 1, "file_id": 2},
        "retrieve_chunks": {"query": "q", "knowledge_base_ids": [118]},
        "search_knowledge": {"query": "q", "knowledge_base_ids": [118]},
        "create_document": {"knowledge_id": 1, "file_name": "a.md", "content": "x"},
        "upload_file": {"knowledge_id": 1, "file_name": "a.txt", "content_base64": "YQ=="},
    }
    async with server(monkeypatch, identity_resolver=resolver) as (app, calls, _):
        async with session(app) as client:
            tools = (await client.list_tools()).tools
            for tool in tools:
                assert "external_id" in tool.inputSchema["required"]
                assert tool.inputSchema["properties"]["external_id"]["type"] == "string"
                result = await client.call_tool(tool.name, arguments[tool.name])
                assert result.isError
        assert not calls
        resolver.assert_not_called()
        audits = [record.message for record in caplog.records if "mcp tool=" in record.message]
        assert len(audits) == 10 and all("user_id=None tenant_id=None" in line for line in audits)


@pytest.mark.parametrize("value", [None, 7, True, "", " ", "sensitive-account-" * 20])
async def test_sdk_rejects_invalid_accounts_before_resolution(monkeypatch, value):
    """F081 AC-01, AC-03, AC-09: SDK 非法账号拒绝且不回显输入。"""
    resolver = AsyncMock(side_effect=AssertionError("must not resolve"))
    async with server(monkeypatch, identity_resolver=resolver) as (app, _, _):
        async with session(app) as client:
            result = await client.call_tool(
                "search_knowledge", {"external_id": value, "query": "q", "knowledge_base_ids": [118]}
            )
            assert result.isError and "sensitive-account-" not in str(result)
        resolver.assert_not_called()


@pytest.mark.parametrize("tool", ["search_knowledge", "list_knowledge"])
async def test_identity_timeout_prevents_business_and_audits_no_actor(monkeypatch, caplog, tool):
    """F081 AC-08, AC-09: 两入口身份超时释放作用域。不使用 Token 充当执行用户。"""
    import logging

    released = []

    async def resolve(principal, external_id):
        try:
            await asyncio.Event().wait()
        finally:
            released.append(True)

    for module in ["tool_runtime", "search_service"]:
        monkeypatch.setattr(f"bisheng.mcp_server.domain.services.{module}.IDENTITY_TIMEOUT_SECONDS", 0.02)
    caplog.set_level(logging.INFO)
    async with server(monkeypatch, identity_resolver=resolve) as (app, calls, active):
        app.routes[0].endpoint.tool_runtime.factory = AsyncMock(side_effect=AssertionError("must not open"))
        async with session(app) as client:
            args = {"external_id": "0008"}
            if tool == "search_knowledge":
                args.update(query="q", knowledge_base_ids=[118])
            result = await client.call_tool(tool, args)
            assert result.isError and "timed out" in str(result)
        assert not calls and not active and released == [True]
        assert "token_user_id=7 token_tenant_id=7 user_id=None tenant_id=None" in caplog.text


async def test_one_token_concurrent_accounts_use_distinct_identities(monkeypatch, caplog):
    """F081 AC-04, AC-08, AC-09: 同一 Token 并发账号不串权限或审计身份。"""
    import logging

    @asynccontextmanager
    async def factory(request, user):
        async def list_knowledge(**params):
            assert "external_id" not in params
            await asyncio.sleep(0.01)
            assert get_current_tenant_id() == user.tenant_id
            assert user.user_role == [2]
            return {"data": [{"id": user.user_id}], "page_size": 20, "has_more": False, "next_cursor": None}

        yield SimpleNamespace(list_knowledge=list_knowledge)

    caplog.set_level(logging.INFO)
    async with server(monkeypatch) as (app, _, _):
        app.routes[0].endpoint.tool_runtime.factory = factory
        async with session(app) as client:
            results = await asyncio.gather(
                *[client.call_tool("list_knowledge", {"external_id": account}) for account in ["0007", "0008"]]
            )
            assert [result.structuredContent["data"][0]["id"] for result in results] == [7, 8]
        assert "token_user_id=7 token_tenant_id=7 user_id=8 tenant_id=8" in caplog.text


@pytest.mark.parametrize("tool", ["search_knowledge", "list_knowledge"])
@pytest.mark.parametrize("denied", [True, False])
async def test_identity_failure_is_safe_and_never_opens_business(monkeypatch, tool, denied, caplog):
    """F081 AC-03, AC-08, AC-09: 身份拒绝与设施异常均失败。不回退或泄漏。"""

    async def resolve(principal, external_id):
        if denied:
            raise BaseErrorCode(msg="sensitive-account-detail", code=403, mcp_identity_denied=True)
        raise RuntimeError("sensitive-account-detail")

    async with server(monkeypatch, identity_resolver=resolve) as (app, calls, active):
        factory = AsyncMock(side_effect=AssertionError("must not open"))
        app.routes[0].endpoint.tool_runtime.factory = factory
        async with session(app) as client:
            args = {"external_id": "0008"}
            if tool == "search_knowledge":
                args.update(query="q", knowledge_base_ids=[118])
            result = await client.call_tool(tool, args)
            assert result.isError and "sensitive-account-detail" not in str(result)
            if denied:
                assert "指定账号或当前租户不可用" in str(result)
        factory.assert_not_called()
        assert not calls and not active and "sensitive-account-detail" not in caplog.text


@pytest.mark.parametrize(
    "tool,args",
    [
        ("list_knowledge", {"user_id": 1}),
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
            result = await client.call_tool(tool, {"external_id": "0007", **args})
            assert result.isError
        factory.assert_not_called()


async def test_new_tool_schemas_and_annotations(monkeypatch):
    """AC-02, AC-17: every new tool is strict and writes are described accurately."""
    async with server(monkeypatch) as (app, _, _):
        async with session(app) as client:
            tools = (await client.list_tools()).tools
            for tool in tools:
                assert tool.inputSchema["additionalProperties"] is False
                assert not {"user_id", "tenant_id", "file_path"} & tool.inputSchema["properties"].keys()
                assert tool.outputSchema
                assert "external_id" not in tool.outputSchema.get("properties", {})
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
            assert "external_id" not in scope["properties"]
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
                result = await client.call_tool(name, {"external_id": "0007", **args})
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
            result = await client.call_tool(
                "list_files", {"external_id": "0007", "knowledge_id": 1, "folder_id": folder_id}
            )
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
                return await client.call_tool(
                    "list_knowledge", {"external_id": "0008" if token == "second" else "0007"}
                )

        first, second = await asyncio.gather(invoke("first"), invoke("second"))
        assert first.structuredContent["data"] == [{"id": 7}]
        assert second.structuredContent["data"] == [{"id": 8}]
        async with session(app) as client:
            error = await client.call_tool("list_knowledge", {"external_id": "0007", "name": "failure"})
            assert error.isError and "sensitive-connection" not in str(error)
    assert not active and "sensitive-connection-password" not in caplog.text
