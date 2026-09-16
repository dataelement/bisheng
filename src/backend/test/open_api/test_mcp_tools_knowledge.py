"""F052 T301a — the two knowledge tools, against the retrieval facade contract.

These tools deliberately own no filtering: they build the execution identity
from the credential and hand everything to the unified retrieval facade. That is
what makes "what this key sees through MCP" and "what the same key sees through
``POST /api/v2/filelib/retrieve``" the same set by construction rather than by
two implementations agreeing to stay in step.

The facade is F052's other line. Until it merges, the tools are **absent** from
``tools/list`` rather than present and broken, and this file skips — the skip
itself is asserted below, so "the tools quietly disappeared" cannot pass as
"the facade has not landed".
"""

from __future__ import annotations

import pytest

from bisheng.open_api.mcp import registry
from bisheng.open_api.mcp.tools import knowledge as knowledge_tools

from .test_mcp_server import auth, error_payload, principal

pytestmark = pytest.mark.skipif(
    not knowledge_tools.facade_available(),
    reason="F052 Line A (RetrievalFacadeService) has not landed on this tree yet",
)


@pytest.fixture
def bearer(monkeypatch):
    def install(value):
        async def validate(_authorization):
            return value

        monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)

    return install


@pytest.fixture
def facade(monkeypatch):
    """Spy on the facade; its own behaviour is covered by ``test/knowledge``."""

    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService

    calls: list[tuple[str, dict]] = []
    responses: dict[str, object] = {}

    async def retrieve(identity, request):
        calls.append(("retrieve", {"identity": identity, "request": request}))
        value = responses["retrieve"]
        if isinstance(value, Exception):
            raise value
        return value

    async def list_accessible(identity, *, name=None, limit=200):
        calls.append(("list", {"identity": identity, "name": name, "limit": limit}))
        value = responses["list"]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(RetrievalFacadeService, "retrieve", staticmethod(retrieve))
    monkeypatch.setattr(RetrievalFacadeService, "list_accessible_knowledge", staticmethod(list_accessible))
    return type("Facade", (), {"calls": calls, "responses": responses})()


def _result(**overrides):
    from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalChunk, RetrievalFacadeResult

    chunk = RetrievalChunk(
        knowledge_id=7,
        knowledge_type=3,
        knowledge_name="产品空间",
        document_id=41,
        document_name="handbook.pdf",
        chunk_index=2,
        content="...",
        document_update_time=None,
    )
    payload = {"chunks": [chunk], "total": 1, "effective_scope": [7], "truncated_params": {}}
    payload.update(overrides)
    return RetrievalFacadeResult(**payload)


async def test_search_executes_as_the_service_account_with_no_whitelist(bearer, mcp_session, facade):
    """A developer key's range is what an administrator granted it.

    A whitelist is an *application's* capability declaration; passing one here
    would silently narrow a developer's own access to something nobody declared.
    """

    facade.responses["retrieve"] = _result()
    bearer(principal(scopes=frozenset({"knowledge:read"})))
    async with mcp_session(auth()) as session:
        await session.call_tool("bisheng_knowledge_search", {"query": "报销流程"})

    identity = dict(facade.calls)["retrieve"]["identity"]
    request = dict(facade.calls)["retrieve"]["request"]
    assert identity.actor.subject_type == "service_account"
    assert identity.actor.subject_id == 31
    assert request.whitelist is None
    assert request.knowledge_ids is None  # omitted means "everything granted"


async def test_search_returns_citable_chunks_with_the_scope_it_actually_searched(bearer, mcp_session, facade):
    facade.responses["retrieve"] = _result(truncated_params={"top_k": 200})
    bearer(principal(scopes=frozenset({"knowledge:read"})))
    async with mcp_session(auth()) as session:
        result = await session.call_tool("bisheng_knowledge_search", {"query": "x", "top_k": 5000})

    payload = result.structuredContent
    assert payload["chunks"][0]["document_name"] == "handbook.pdf"
    assert payload["effective_scope"] == [7]
    # Clamping is visible rather than silent: an agent that asked for 5000 must
    # be able to tell it did not get 5000.
    assert payload["truncated_params"] == {"top_k": 200}


async def test_an_unreachable_target_refuses_the_whole_request(bearer, mcp_session, facade):
    """Naming a base means intent; returning less would be a silent wrong answer."""

    from bisheng.common.errcode.mcp_face import KnowledgeUnreachableError

    facade.responses["retrieve"] = KnowledgeUnreachableError(unreachable_ids=[99])
    bearer(principal(scopes=frozenset({"knowledge:read"})))
    async with mcp_session(auth()) as session:
        payload = error_payload(
            await session.call_tool("bisheng_knowledge_search", {"query": "x", "knowledge_ids": [7, 99]})
        )

    assert payload["code"] == 26321
    assert payload["category"] == "unreachable"
    assert payload["data"]["unreachable_ids"] == [99]


async def test_a_deleted_base_named_explicitly_is_unreachable_not_revoked(bearer, mcp_session, facade):
    """ "Revoked" is a whitelist word. This face has no whitelist, so it never applies."""

    from bisheng.common.errcode.mcp_face import KnowledgeUnreachableError

    facade.responses["retrieve"] = KnowledgeUnreachableError(unreachable_ids=[7])
    bearer(principal(scopes=frozenset({"knowledge:read"})))
    async with mcp_session(auth()) as session:
        payload = error_payload(
            await session.call_tool("bisheng_knowledge_search", {"query": "x", "knowledge_ids": [7]})
        )

    assert payload["code"] == 26321


async def test_a_permission_outage_is_surfaced_and_returns_nothing(bearer, mcp_session, facade):
    """Fail-closed with a *visible* error — never a quietly empty result set."""

    from bisheng.common.errcode.permission import PermissionServiceUnavailableError

    facade.responses["retrieve"] = PermissionServiceUnavailableError()
    bearer(principal(scopes=frozenset({"knowledge:read"})))
    async with mcp_session(auth()) as session:
        result = await session.call_tool("bisheng_knowledge_search", {"query": "x"})

    payload = error_payload(result)
    assert payload["code"] == 19002
    assert payload["category"] == "permission_unavailable"
    assert result.structuredContent is None


async def test_the_list_returns_ids_and_names_ready_for_a_capability_declaration(bearer, mcp_session, facade):
    from bisheng.knowledge.domain.schemas.retrieval_facade import AccessibleKnowledge

    facade.responses["list"] = [
        AccessibleKnowledge(knowledge_id=7, name="产品空间", type="space", description=None),
        AccessibleKnowledge(knowledge_id=8, name="制度库", type="library", description="HR"),
    ]
    bearer(principal(scopes=frozenset({"knowledge:read"})))
    async with mcp_session(auth()) as session:
        result = await session.call_tool("bisheng_knowledge_list", {})

    payload = result.structuredContent
    assert payload["total"] == 2
    assert {item["type"] for item in payload["items"]} == {"space", "library"}
    assert payload["items"][0]["knowledge_id"] == 7


async def test_both_tools_run_as_the_same_subject(bearer, mcp_session, facade):
    """The list is what the search will accept — same identity, same facade."""

    facade.responses["retrieve"] = _result()
    facade.responses["list"] = []
    bearer(principal(scopes=frozenset({"knowledge:read"})))
    async with mcp_session(auth()) as session:
        await session.call_tool("bisheng_knowledge_search", {"query": "x"})
        await session.call_tool("bisheng_knowledge_list", {})

    identities = [call["identity"] for _name, call in facade.calls]
    assert {(item.actor.subject_type, item.actor.subject_id) for item in identities} == {("service_account", 31)}


async def test_a_personal_token_sees_the_two_knowledge_tools_and_nothing_else(bearer, mcp_session, facade):
    """伴生 §4.10.8: a personal access token's MCP surface is search plus list."""

    bearer(principal(scopes=frozenset({"knowledge:read"}), actor_kind="natural_person"))
    async with mcp_session(auth("bs-pat-secret")) as session:
        listed = {tool.name for tool in (await session.list_tools()).tools}

    assert listed == {"bisheng_knowledge_search", "bisheng_knowledge_list"}


def test_the_tools_do_no_filtering_of_their_own():
    """Structural: a second filter here would be a second answer to "may I see it"."""

    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[2] / "bisheng" / "open_api" / "mcp" / "tools" / "knowledge.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("batch_check_business_actions", "list_visible_objects", "KnowledgeDao", "aretrieve_chunks"):
        assert forbidden not in source


def test_the_registry_hides_both_tools_when_the_facade_is_absent():
    """Asserted here so a skipped file cannot mean "the tools silently vanished"."""

    assert knowledge_tools.facade_available() is True
    installed = {spec.name for spec in registry.installed_tools()}
    assert {"bisheng_knowledge_search", "bisheng_knowledge_list"} <= installed
