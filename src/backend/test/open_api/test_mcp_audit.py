"""F052 T204a — one audit row per tool call, attributable, and free of content.

Two failure modes this guards, both of which look fine from the outside:

* **Double writing.** The generic ``/api/v2`` middleware would also record every
  MCP request, as ``POST /api/v2/mcp`` — true and useless. Two rows per call,
  one of which says nothing about what was done.
* **The corpus leaking into the audit table.** A retrieval query and the chunks
  it returns are knowledge-base content. Copying them into an access log turns
  it into a second copy of the corpus with different retention and different
  readers.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from bisheng.database.models.audit_log import _UI_VISIBLE_V2_ACTIONS
from bisheng.open_api.mcp import registry
from bisheng.open_api.mcp.audit import MCP_TARGET_TYPE, MCP_TOOL_CALL_ACTION, TARGET_KEYS

from .test_mcp_server import auth, principal

REPO = pathlib.Path(__file__).resolve().parents[4]


@pytest.fixture
def bearer(monkeypatch):
    def install(value):
        async def validate(_authorization):
            return value

        monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)

    return install


@pytest.fixture
def rows(monkeypatch):
    """Capture what the batched writer is handed, without a database."""

    captured: list = []

    from bisheng.open_api.domain.services.call_audit_service import open_api_call_audit_service

    monkeypatch.setattr(open_api_call_audit_service, "enqueue", captured.append)
    return captured


@pytest.fixture
def org_tree(monkeypatch):
    async def tree():
        return []

    monkeypatch.setattr("bisheng.open_api.mcp.tools.identity.OrgDirectoryService.atree", staticmethod(tree))


async def test_a_successful_call_is_attributable_to_the_key_and_its_service_account(
    bearer, mcp_session, rows, org_tree
):
    bearer(principal(scopes=frozenset({"identity:read"})))
    async with mcp_session(auth()) as session:
        await session.call_tool("bisheng_org_tree", {})

    row = next(row for row in rows if row.target_id == "bisheng_org_tree")
    assert (row.action, row.target_type) == (MCP_TOOL_CALL_ACTION, MCP_TARGET_TYPE)
    assert row.tenant_id == 9
    # A service account is named rather than counted as an operator: the row
    # should read as "this key did it", not as an action by whoever owns it.
    assert row.operator_id == 0
    assert row.operator_name == "indexer"
    metadata = row.audit_metadata
    assert metadata["credential_id"] == 7
    assert metadata["actor_kind"] == "service_account"
    assert metadata["actor_id"] == 31
    assert metadata["resource_owner_user_id"] == 12
    assert metadata["tool"] == "bisheng_org_tree"
    assert metadata["category"] == registry.CATEGORY_IDENTITY
    assert metadata["outcome"] == "success"
    assert isinstance(metadata["latency_ms"], int)
    assert "trace_id" in metadata


async def test_a_refused_call_records_the_code_it_was_refused_with(bearer, mcp_session, rows):
    bearer(principal(scopes=frozenset({"knowledge:read"})))
    async with mcp_session(auth()) as session:
        await session.call_tool("bisheng_org_tree", {})

    row = next(row for row in rows if row.target_id == "bisheng_org_tree")
    assert row.audit_metadata["outcome"] == "denied:26302"


async def test_a_refusal_at_the_door_is_on_the_same_timeline(bearer, mcp_http, rows):
    """A ``delegate`` key never reaches a tool, but the attempt is still auditable.

    Same action with ``target_id="-"`` rather than a second action: "this key was
    refused" and "this key called a tool" belong on one timeline, and splitting
    them means two filters to remember on the audit page.
    """

    bearer(principal(delegate=True))
    async with mcp_http(auth()) as client:
        await client.post("/api/v2/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    row = next(row for row in rows if row.action == MCP_TOOL_CALL_ACTION)
    assert row.target_id == "-"
    assert row.audit_metadata["outcome"] == "denied:26051"


async def test_the_query_text_and_its_results_never_reach_the_audit_table(bearer, mcp_session, rows, monkeypatch):
    """The target summary is ids. Content stays in the knowledge base."""

    async def members(dept_id, **_kwargs):
        return {"members": [{"user_id": 1, "user_name": "secret-person", "status": "active"}], "total": 1}

    monkeypatch.setattr("bisheng.open_api.mcp.tools.identity.OrgDirectoryService.amembers", staticmethod(members))
    bearer(principal(scopes=frozenset({"identity:read"})))
    async with mcp_session(auth()) as session:
        await session.call_tool("bisheng_dept_members", {"dept_id": "BS@rd", "keyword": "confidential-search-term"})

    row = next(row for row in rows if row.target_id == "bisheng_dept_members")
    serialised = json.dumps(row.audit_metadata, ensure_ascii=False)
    assert "confidential-search-term" not in serialised
    assert "secret-person" not in serialised
    assert "bs-sak-" not in serialised
    assert row.audit_metadata["target"] == {"dept_id": "BS@rd"}


async def test_the_target_summary_is_an_allowlist(bearer, mcp_session, rows, org_tree, monkeypatch):
    """A handler that starts passing something new gets it dropped, not leaked."""

    from bisheng.open_api.mcp import audit

    audit.audit_tool_call(
        principal(),
        tool="bisheng_knowledge_search",
        category="knowledge_search",
        target={"knowledge_ids": [1, 2], "query": "secret", "chunk": "body text"},
        outcome="success",
        latency_ms=3,
    )
    assert rows[-1].audit_metadata["target"] == {"knowledge_ids": [1, 2]}
    assert set(TARGET_KEYS) == {"knowledge_ids", "app_id", "table", "dept_id", "user_id"}


@pytest.mark.parametrize(("path", "expected"), [("/api/v2/mcp", 0), ("/api/v2/filelib/retrieve", 1)])
async def test_the_generic_v2_middleware_steps_aside_only_for_this_path(rows, path, expected):
    """Otherwise every tool call costs two rows, one of which says nothing.

    The second case guards the guard: short-circuiting by prefix must not
    accidentally silence the rest of ``/api/v2``.
    """

    from bisheng.open_api.api.middleware import OpenApiAuditMiddleware

    async def inner(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}", "more_body": False})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    await OpenApiAuditMiddleware(inner)(
        {"type": "http", "method": "POST", "path": path, "headers": [], "query_string": b""},
        receive,
        send,
    )

    assert len([row for row in rows if row.action == "open_api.call"]) == expected


def test_the_action_is_registered_in_lockstep_across_all_three_places():
    """Backend only: written and unfindable. Frontend only: an empty filter forever."""

    assert MCP_TOOL_CALL_ACTION in _UI_VISIBLE_V2_ACTIONS

    log_ts = (REPO / "src/frontend/platform/src/controllers/API/log.ts").read_text(encoding="utf-8")
    assert f"'{MCP_TOOL_CALL_ACTION}'" in log_ts

    # The label key is derived by ``actionToI18nKey``, never hand-written.
    key = "openApiMcpToolCall"
    for locale in ("zh-Hans", "en-US", "ja"):
        payload = json.loads(
            (REPO / f"src/frontend/platform/public/locales/{locale}/bs.json").read_text(encoding="utf-8")
        )
        assert payload["log"]["eventTypeEnum"].get(key), locale
