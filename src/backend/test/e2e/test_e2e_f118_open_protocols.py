"""T210: two real v2/MCP journeys, local collection until upgraded live ready.

Uses the existing F118_E2E=1/private-auth/model/verified-SHA opt-in contract.
No web JWT is used as a v2 or MCP credential. MCP uses the existing official
ClientSession helper, which negotiates initialize/initialized, protocol version
and optional session ID; the server is stateless, so no session ID is invented.
The actual bisheng-sdk public retrieve client additionally requires a real
hosted application token + visitor context. This suite does not pretend that a
service-account bearer is an app credential or claim that SDK journey passed.
No environment writes occur during --collect-only; neither journey is UI proof.
"""

from __future__ import annotations

import base64
import os

import httpx
import pytest
import pytest_asyncio

from test.e2e.helpers.f118_open_protocols import F118OpenProtocols
from test.e2e.helpers.open_mcp import call_error, call_success, open_mcp_session

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(os.environ.get("F118_E2E") != "1", reason="requires upgraded isolated F118 and explicit opt-in"),
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def protocols():
    async with httpx.AsyncClient(timeout=60, trust_env=False, follow_redirects=False) as client:
        fixture = F118OpenProtocols.from_environment(client)
        try:
            await fixture.prepare()
            yield fixture
        finally:
            await fixture.cleanup()


async def test_ac35_ac65_ac67_v2_old_zero_upload_retrieve_and_scope_tenant_refusals(protocols):
    """AC-10/30/35/36/65/66/67/68/79: real SA scope, worker, Doc/V1 and physical SPACE3."""
    p, env = protocols, protocols.target
    marker = env.prefix + "v2-actual-indexed-text"
    created = await p.v2(
        "POST",
        "/filelib/",
        json={
            "name": env.name("legacy"),
            "type": 0,
            "model": str(env.embedding(0)["id"]),
        },
    )
    sid = created["id"]
    await p.assert_native(created, "legacy")
    page = await p.v2("GET", "/filelib/", params={"type": 0, "name": created["name"], "page_size": 200})
    assert any(row["id"] == sid and row["type"] == 0 for row in page["data"])
    uploaded = await p.v2(
        "POST", f"/filelib/file/{sid}", files={"file": (env.prefix + "v2.txt", (marker + "\n").encode(), "text/plain")}
    )
    fid = uploaded["id"]
    await p.assert_worker_and_version(sid, fid)
    files = await p.v2("GET", "/filelib/file/list", params={"knowledge_id": sid, "page_size": 200})
    assert fid in {row["id"] for row in files["data"]}
    body = {"query": marker, "knowledge_base_ids": [sid], "top_k": 10}
    found = await p.v2("POST", "/filelib/retrieve", json=body)
    assert found["total"] > 0 and found["chunks"]
    assert {row["knowledge_id"] for row in found["chunks"]} == {sid}
    assert any(marker in row["content"] for row in found["chunks"])

    await p.refused(
        "POST",
        "/filelib/",
        26003,
        403,
        key=p.keys["read"],
        json={
            "name": env.name("copy-source"),
            "type": 0,
            "model": str(env.embedding(0)["id"]),
        },
    )
    after = await env.ok("GET", "/knowledge/space/list", params={"keyword": env.name("copy-source"), "page_size": 200})
    assert not after["data"]
    foreign = p.foreign_space
    await p.refused("POST", "/filelib/retrieve", 26321, 404, json={**body, "knowledge_base_ids": [foreign["id"]]})
    await p.refused("POST", "/filelib/retrieve", 26321, 404, key=p.keys["foreign"], json=body)
    foreign_page = await p.v2("GET", "/filelib/", params={"type": 0, "name": foreign["name"]})
    assert not foreign_page["data"]
    # The same real scoped key deletes only after explicit resource authorization.
    await p.grant_delete(sid)
    await p.v2("DELETE", f"/filelib/{sid}")
    await p.wait_absent(sid)
    page = await p.v2("GET", "/filelib/", params={"type": 0, "name": created["name"]})
    assert not page["data"]


async def test_ac35_ac66_mcp_initialized_catalog_upload_retrieve_and_delete(protocols):
    """AC-10/31/35/36/65/66/67/68/79: actual MCP SDK negotiation and scoped tools-call, no JWT fallback."""
    p, env = protocols, protocols.target
    marker = env.prefix + "mcp-actual-indexed-text"
    required = {
        "bisheng_knowledge_create",
        "bisheng_knowledge_list",
        "bisheng_knowledge_file_upload",
        "bisheng_knowledge_file_list",
        "bisheng_knowledge_retrieve",
        "bisheng_knowledge_delete",
    }
    async with open_mcp_session(p.mcp_url, p.keys["read"].plaintext) as session:
        names = {tool.name for tool in (await session.list_tools()).tools}
        assert {"bisheng_knowledge_list", "bisheng_knowledge_retrieve"}.issubset(names)
        assert "bisheng_knowledge_create" not in names and "bisheng_knowledge_delete" not in names
        await call_error(
            session,
            "bisheng_knowledge_create",
            {
                "name": env.name("copy-result"),
                "type": 0,
                "model": str(env.embedding(0)["id"]),
            },
            expected_code="PERMISSION_DENIED",
        )
    after = await env.ok("GET", "/knowledge/space/list", params={"keyword": env.name("copy-result"), "page_size": 200})
    assert not after["data"]
    async with open_mcp_session(p.mcp_url, p.keys["full"].plaintext) as session:
        assert required.issubset({tool.name for tool in (await session.list_tools()).tools})
        created = await call_success(
            session,
            "bisheng_knowledge_create",
            {
                "name": env.name("native"),
                "type": 0,
                "model": str(env.embedding(0)["id"]),
            },
        )
        sid = created["id"]
        await p.assert_native(created, "native")
        listed = await call_success(
            session, "bisheng_knowledge_list", {"type": 0, "name": created["name"], "page_size": 200}
        )
        assert any(row["id"] == sid and row["type"] == 0 for row in listed["data"])
        uploaded = await call_success(
            session,
            "bisheng_knowledge_file_upload",
            {
                "knowledge_id": sid,
                "file_name": env.prefix + "mcp.txt",
                "content_base64": base64.b64encode((marker + "\n").encode()).decode(),
            },
        )
        fid = uploaded["id"]
        await p.assert_worker_and_version(sid, fid)
        files = await call_success(session, "bisheng_knowledge_file_list", {"knowledge_id": sid, "page_size": 200})
        assert fid in {row["id"] for row in files["data"]}
        body = {"query": marker, "knowledge_base_ids": [sid], "top_k": 10}
        found = await call_success(session, "bisheng_knowledge_retrieve", body)
        assert found["total"] > 0 and {row["knowledge_id"] for row in found["chunks"]} == {sid}
        assert any(marker in row["content"] for row in found["chunks"])
        foreign = p.foreign_space
        await call_error(
            session, "bisheng_knowledge_retrieve", {**body, "knowledge_base_ids": [foreign["id"]]}, expected_code=26321
        )
        await p.grant_delete(sid)
        deleted = await call_success(session, "bisheng_knowledge_delete", {"knowledge_id": sid})
        assert deleted["success"] is True
        await p.wait_absent(sid)
        listed = await call_success(session, "bisheng_knowledge_list", {"type": 0, "name": created["name"]})
        assert not listed["data"]
