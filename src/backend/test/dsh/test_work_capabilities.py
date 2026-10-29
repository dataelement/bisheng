"""AC-02..05: publication, live permission checks and immutable skill downloads."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from jsonschema import ValidationError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

from bisheng.dsh.domain.services.work_capabilities import WorkCapabilitiesService
from bisheng.dsh.work_mcp import WorkMcpResponse, create_work_mcp_runtime


class Publications:
    def __init__(self):
        self.audit = AsyncMock()
        self.rows = {(2, "tool"): {7}, (2, "skill"): {9}}

    async def list_enabled(self, tenant, kind):
        return self.rows.get((tenant, kind), set())

    async def save(self, tenant, kind, resource_id, enabled):
        row = self.rows.setdefault((tenant, kind), set())
        if enabled:
            row.add(resource_id)
        else:
            row.discard(resource_id)


class Query(BaseModel):
    query: str


def service():
    value = WorkCapabilitiesService(SimpleNamespace(tenant_id=2, user_id=42), Publications())
    value._tools = AsyncMock(return_value={7: SimpleNamespace(id=7, name="Customer query", desc="Search customers")})
    value._skills = AsyncMock(
        return_value={
            9: SimpleNamespace(
                id=9, name="report", display_name="Report", description="Build a report", content_hash="a" * 64
            )
        }
    )
    executor = SimpleNamespace(
        args_schema=Query, get_input_schema=lambda: Query, ainvoke=AsyncMock(return_value={"customer": "Allowed"})
    )
    value._executor = AsyncMock(return_value=executor)
    return value


async def test_tool_directory_and_execution_recheck_permission_and_publication():
    app = service()
    catalog = await app.list_tools()
    assert catalog[0]["name"] == "bisheng_tool_7"
    assert catalog[0]["inputSchema"]["required"] == ["query"]
    assert await app.call_tool("bisheng_tool_7", {"query": "test"}) == {"customer": "Allowed"}
    app._tools.return_value = {}
    with pytest.raises(HTTPException) as denied:
        await app.call_tool("bisheng_tool_7", {"query": "test"})
    assert denied.value.status_code == 403
    app._executor.return_value.ainvoke.assert_awaited_once()
    assert await app.list_tools() == []


async def test_publication_control_is_retired_in_favor_of_resource_permissions():
    app = service()
    with pytest.raises(HTTPException) as retired:
        await app.publish("tool", 7, False)
    assert retired.value.status_code == 410
    assert len(await app.list_tools()) == 1


async def test_arguments_are_validated_before_execution_and_failures_propagate():
    app = service()
    with pytest.raises(ValidationError):
        await app.call_tool("bisheng_tool_7", {"query": 10})
    app._executor.return_value.ainvoke.assert_not_awaited()
    app._executor.return_value.ainvoke.side_effect = RuntimeError("upstream failure")
    with pytest.raises(RuntimeError):
        await app.call_tool("bisheng_tool_7", {"query": "test"})


@pytest.mark.parametrize(
    "uri",
    [
        "bisheng-skill://3/9/" + "a" * 64,
        "bisheng-skill://2/9/" + "b" * 64,
        "file:///etc/passwd",
        "bisheng-skill://2/10/" + "a" * 64,
    ],
)
async def test_skill_rejects_other_tenants_versions_and_unpublished_ids(uri):
    app = service()
    with pytest.raises(HTTPException):
        await app.read_skill(uri)


async def test_skill_rechecks_revocation_after_download():
    app = service()
    uri = (await app.list_skills())[0]["uri"]

    def download(skill):
        app._skills.return_value = {}
        return {"files": [], "tool_ids": []}

    app._read_bundle = download
    with pytest.raises(HTTPException) as denied:
        await app.read_skill(uri)
    assert denied.value.status_code == 409


async def test_real_streamable_http_handshake_discovery_and_error_result(monkeypatch):
    app_service = service()
    monkeypatch.setattr("bisheng.dsh.work_mcp.WorkCapabilitiesService", lambda user: app_service)
    manager = create_work_mcp_runtime(
        TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["localhost"])
    )

    async def endpoint(request: Request):
        return WorkMcpResponse(manager, app_service.user)

    app = Starlette(routes=[Route("/mcp", endpoint, methods=["POST", "GET"])])
    headers = {"accept": "application/json, text/event-stream", "mcp-protocol-version": "2025-11-25"}
    async with (
        manager.run(),
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost", headers=headers) as client,
    ):

        async def rpc(method, params=None):
            response = await client.post(
                "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
            )
            assert response.status_code == 200, response.text
            return response.json()

        oversized = await client.post("/mcp", content=b"x" * (256 * 1024 + 1))
        assert oversized.status_code == 413
        initialized = await rpc(
            "initialize",
            {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        )
        assert initialized["result"]["serverInfo"]["name"] == "bisheng-enterprise-work"
        assert (await rpc("tools/list"))["result"]["tools"][0]["name"] == "bisheng_tool_7"
        result = await rpc("tools/call", {"name": "bisheng_tool_7", "arguments": {"query": "test"}})
        assert result["result"]["structuredContent"]["result"]["customer"] == "Allowed"
        app_service._tools.return_value = {}
        result = await rpc("tools/call", {"name": "bisheng_tool_7", "arguments": {"query": "test"}})
        assert result["result"]["isError"] is True
        assert json.loads(result["result"]["content"][0]["text"])["code"] == 403
        assert (await rpc("resources/list"))["result"]["resources"][0]["uri"].endswith("a" * 64)


async def test_audit_failure_prevents_execution_and_records_only_safe_metadata():
    app = service()
    app.publications.audit.side_effect = RuntimeError("audit storage unavailable")
    with pytest.raises(RuntimeError):
        await app.call_tool("bisheng_tool_7", {"query": "private customer"})
    app._executor.return_value.ainvoke.assert_not_awaited()
    assert "private customer" not in str(app.publications.audit.call_args)
    app.publications.audit.side_effect = None
    app.publications.audit.reset_mock()
    await app.call_tool("bisheng_tool_7", {"query": "private customer"})
    records = [call.args[-1] for call in app.publications.audit.call_args_list]
    assert [row["status"] for row in records] == ["STARTED", "SUCCEEDED"]
    assert records[0]["operation_id"] == records[1]["operation_id"]


def test_work_transport_uses_platform_origin_independently_of_external_mcp():
    from bisheng.dsh.work_mcp import work_transport_security

    security = work_transport_security("http://192.168.106.119:3007")
    assert security.enable_dns_rebinding_protection is True
    assert security.allowed_hosts == ["192.168.106.119:3007", "192.168.106.119"]
    assert security.allowed_origins == ["http://192.168.106.119:3007"]
    with pytest.raises(ValueError):
        work_transport_security("https://user:password@example.com")


@pytest.mark.parametrize(
    "metadata",
    [
        {"metadata": {"bisheng-work": {"tool_ids": [True]}}},
        {"metadata": []},
        {"metadata": {"bisheng-work": {"tool_ids": [0]}}},
    ],
)
def test_skill_dependencies_require_explicit_positive_tool_ids(metadata):
    with pytest.raises(HTTPException):
        WorkCapabilitiesService._dependencies(metadata)


def test_skill_dependencies_preserve_declared_ids_and_default_to_empty():
    assert WorkCapabilitiesService._dependencies({}) == []
    assert WorkCapabilitiesService._dependencies({"metadata": {"bisheng-work": {"tool_ids": [7, 8]}}}) == [7, 8]
