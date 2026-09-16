"""F052 T302 — the whole MCP face driven by a real client, at the layer that can prove it.

覆盖 AC: AC-01, AC-05

T302 as written bundles two kinds of claim. One kind is about **this face**: a
standard MCP client connects with nothing but an address and a bearer, and a
credential that stopped being valid stops working on the very next call. Those
are decided entirely inside the request path, so they are asserted here, against
a genuine ``ClientSession`` speaking streamable HTTP over the app in-process —
hand-rolled JSON-RPC posts would keep passing with a broken handshake.

The other kind is about **the stores agreeing** (AC-40 / AC-41 set equality over
seeded samples, AC-44 with OpenFGA actually stopped). Those need MySQL, Redis,
OpenFGA and Milvus/ES up together; they are still owed to the CI middleware
stage and are listed at the bottom of
``test/knowledge/test_retrieval_facade_equality.py`` rather than stubbed here.
A skipped placeholder reads as coverage while proving nothing.

AC-45 is not duplicated here either: ``test_mcp_scope_matrix.py`` already walks
the registry over this same in-process app without stubbing the handlers.
"""

from __future__ import annotations

import pytest

from bisheng.app_publish.domain.services.app_credential_service import REVOCATION_BOUND_SECONDS
from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
from bisheng.core.config.open_platform import OpenApiConf
from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService
from bisheng.open_api.mcp.tools import knowledge as knowledge_tools

from .test_mcp_server import _http_errors, auth, principal, tool_names


@pytest.fixture
def validator(monkeypatch):
    """Install a credential validator and count how often the face consults it."""

    state: dict = {"principal": None, "raises": None, "calls": 0}

    async def validate(_authorization):
        state["calls"] += 1
        if state["raises"] is not None:
            raise state["raises"]
        return state["principal"]

    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    return state


# ---------------------------------------------------------------------------
# AC-01 — any standard client, no local plugin
# ---------------------------------------------------------------------------


async def test_a_standard_client_connects_lists_and_calls_with_nothing_but_an_address_and_a_key(
    validator, mcp_session, monkeypatch
):
    """The full DEV-01 ⑤ walk: handshake → tools/list → tools/call, no shim anywhere.

    The knowledge list tool is the one to call: it is the first thing an agent
    reaches for (it hands out the ids the search tool needs), and it exercises
    the whole chain — gate, registry, handler, facade, output schema.
    """

    async def list_accessible_knowledge(_identity, *, name=None, limit=200):
        item = knowledge_tools.AccessibleKnowledgeItem(knowledge_id=8, name="Handbook", type="space")
        return [item]

    monkeypatch.setattr(RetrievalFacadeService, "list_accessible_knowledge", list_accessible_knowledge)
    validator["principal"] = principal(scopes=frozenset({"knowledge:read"}))

    async with mcp_session(auth()) as session:
        listed = tool_names(await session.list_tools())
        result = await session.call_tool("bisheng_knowledge_list", {})

    assert {"bisheng_knowledge_search", "bisheng_knowledge_list"} <= listed
    assert not result.isError, result
    assert result.structuredContent["items"][0]["knowledge_id"] == 8
    assert result.structuredContent["total"] == 1


# ---------------------------------------------------------------------------
# AC-05 — revocation takes effect on the next call, within 5 seconds
# ---------------------------------------------------------------------------


async def test_a_live_session_is_not_a_grant_the_credential_is_reread_every_call(validator, mcp_session, monkeypatch):
    """An open session must not be a period during which the key is assumed good.

    Counted rather than inferred: if the face ever memoised the principal per
    session, revocation could only take effect on reconnect, and AC-05's bound
    would be unenforceable no matter how short the cache TTL is.

    The directory service is answered at the service boundary: letting the
    handler reach a database that is not there leaves the engine in a state
    that fails *later* files in the same run.
    """

    async def tree():
        return []

    monkeypatch.setattr("bisheng.open_api.mcp.tools.identity.OrgDirectoryService.atree", staticmethod(tree))
    validator["principal"] = principal(scopes=frozenset({"identity:read"}))

    async with mcp_session(auth()) as session:
        after_handshake = validator["calls"]
        await session.list_tools()
        await session.call_tool("bisheng_org_tree", {})

    assert after_handshake >= 1, "the handshake itself must be admitted, not deferred to the first call"
    assert validator["calls"] >= after_handshake + 2, (
        f"only {validator['calls']} validations for handshake + list + call: "
        "something on this path is trusting the session instead of the credential"
    )


async def test_a_revoked_credential_is_refused_on_the_very_next_call(validator, mcp_session):
    """Revoked mid-session → the next request is refused at the transport, not served.

    The refusal reaches the client as a transport failure (HTTP 401) rather than
    a tool error, which is what makes it impossible for an agent to mistake it
    for "that tool is having a bad day".
    """

    validator["principal"] = principal(scopes=frozenset({"identity:read"}))

    with pytest.raises(BaseException) as raised:
        async with mcp_session(auth()) as session:
            assert "bisheng_org_tree" in tool_names(await session.list_tools())
            validator["raises"] = OpenApiCredentialInvalidError()
            await session.list_tools()

    assert [error.response.status_code for error in _http_errors(raised.value)] == [401]


def test_the_credential_cache_can_never_outlive_the_revocation_bound():
    """The MCP face inherits ``validate_bearer``'s Redis cache, so it inherits its cap.

    A deployment that sets this to 300 would leave a revoked key working for
    five minutes on every face at once, and nothing in the request path would
    look wrong. The clamp is the only thing standing between AC-05 and that, so
    it is pinned here rather than left to whoever edits the config model next.

    The bound is imported rather than re-typed: AC-05 and F055's INV-28 are the
    same five seconds, and a local copy would keep asserting the old number
    after someone moved the real one.
    """

    assert OpenApiConf(credential_cache_ttl_seconds=300).credential_cache_ttl_seconds == REVOCATION_BOUND_SECONDS
    assert OpenApiConf().credential_cache_ttl_seconds <= REVOCATION_BOUND_SECONDS
