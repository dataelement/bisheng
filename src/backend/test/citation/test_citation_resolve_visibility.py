"""F029 tests for CitationResolveService view_file filtering.

Covers the new ``_filter_visible_rag_items`` helper and its integration
with ``resolve_citations`` / ``resolve_citation``.

ACs covered:
- AC-15: logged-in user with all RAG documents visible — items returned in
  full (URLs / bbox populated).
- AC-16: partial visibility — invisible citations are removed entirely
  (no documentName / knowledgeId / snippet placeholder).
- AC-17: all citation documents invisible — empty ``items`` array.
- AC-18: single ``resolve_citation`` for an inaccessible RAG citation
  raises NotFoundError.
- AC-19: web citations bypass the view_file filter.
- AC-20: **overridden by F054** (release-contract table 4). The low-level
  helpers (``_filter_visible_rag_items`` / ``_apply_tier_filter``) still apply
  no gating when handed ``permitted=None``, and the tests below still assert
  that. What changed is the public entry: ``resolve_citation`` /
  ``resolve_citations`` now refuse knowledge and article sources outright when
  there is no logged-in user, because AC-20's anonymous pass-through was what
  let a share link hand out the knowledge files behind it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationItemSchema,
    RagCitationPayloadSchema,
    WebCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_resolve_service import (
    CitationResolveService,
)
from bisheng.common.errcode.http_error import NotFoundError


def _make_rag_item(citation_id: str, knowledge_id: int, document_id: int) -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.RAG,
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=knowledge_id,
            documentId=document_id,
            documentName=f"file-{document_id}.pdf",
            snippet="hello",
            items=[RagCitationItemSchema(itemId=f"i-{document_id}")],
        ),
    )


def _make_web_item(citation_id: str) -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.WEB,
        sourcePayload=WebCitationPayloadSchema(
            url="https://example.com",
            title="Example",
        ),
    )


def _make_service() -> CitationResolveService:
    repo = MagicMock()
    repo.list_citations_by_ids = AsyncMock(return_value=[])
    repo.get_citation = AsyncMock(return_value=None)
    return CitationResolveService(repository=repo)


def _stub_enrich_passthrough(svc: CitationResolveService, monkeypatch):
    """Make _enrich_item a no-op identity so tests focus on the filter step."""

    async def fake_enrich(item, login_user, url_allowed=True):
        return item

    monkeypatch.setattr(svc, "_enrich_item", fake_enrich)


def _stub_post_filter(monkeypatch, allowed_by_space: dict[int, set[int]]):
    """Patch KnowledgeFileVisibilityService.post_filter_visible_files."""

    async def fake_post(self, space_id, file_ids):
        return {fid for fid in file_ids if fid in allowed_by_space.get(int(space_id), set())}

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service."
        "KnowledgeFileVisibilityService.post_filter_visible_files",
        fake_post,
    )


# ---------------------------------------------------------------------------
# _filter_visible_rag_items — the new pre-enrich filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filter_visible_rag_items_all_permitted(monkeypatch):
    """All RAG citation documents are visible → items unchanged (AC-15)."""
    svc = _make_service()
    _stub_post_filter(monkeypatch, {5: {1001, 1002}})

    login_user = MagicMock(user_id=7)
    login_user.is_admin = MagicMock(return_value=False)

    items = [
        _make_rag_item("ca", 5, 1001),
        _make_rag_item("cb", 5, 1002),
    ]
    result = await svc._filter_visible_rag_items(items, login_user)

    assert [item.citationId for item in result] == ["ca", "cb"]


@pytest.mark.asyncio
async def test_filter_visible_rag_items_drops_invisible(monkeypatch):
    """Citations whose documentId fails view_file are removed (AC-16)."""
    svc = _make_service()
    _stub_post_filter(monkeypatch, {5: {1001}})

    login_user = MagicMock(user_id=7)
    login_user.is_admin = MagicMock(return_value=False)

    items = [
        _make_rag_item("visible", 5, 1001),
        _make_rag_item("hidden", 5, 1002),  # not in allowed set
    ]
    result = await svc._filter_visible_rag_items(items, login_user)

    assert [item.citationId for item in result] == ["visible"]


@pytest.mark.asyncio
async def test_filter_visible_rag_items_all_invisible_returns_empty(monkeypatch):
    """When no RAG documents are permitted, all RAG items are dropped (AC-17)."""
    svc = _make_service()
    _stub_post_filter(monkeypatch, {5: set()})

    login_user = MagicMock(user_id=7)
    login_user.is_admin = MagicMock(return_value=False)

    items = [
        _make_rag_item("ca", 5, 1001),
        _make_rag_item("cb", 5, 1002),
    ]
    result = await svc._filter_visible_rag_items(items, login_user)
    assert result == []


@pytest.mark.asyncio
async def test_filter_visible_rag_items_keeps_web_citations(monkeypatch):
    """Web citations bypass the view_file filter (AC-19)."""
    svc = _make_service()
    _stub_post_filter(monkeypatch, {5: set()})

    login_user = MagicMock(user_id=7)
    login_user.is_admin = MagicMock(return_value=False)

    items = [
        _make_rag_item("rag_hidden", 5, 1001),
        _make_web_item("web1"),
    ]
    result = await svc._filter_visible_rag_items(items, login_user)
    assert [item.citationId for item in result] == ["web1"]


@pytest.mark.asyncio
async def test_filter_visible_rag_items_anonymous_caller_preserves_all(monkeypatch):
    """login_user=None → this helper still applies no gating.

    F054 refuses anonymous callers one level up (see
    ``test_resolve_citation_anonymous_caller_is_refused``); the helper itself is
    unchanged, so F041's shared/per_user tiering keeps its meaning."""
    svc = _make_service()

    async def fake_post(self, space_id, file_ids):
        raise AssertionError("anonymous caller must not invoke FGA")

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service."
        "KnowledgeFileVisibilityService.post_filter_visible_files",
        fake_post,
    )

    items = [
        _make_rag_item("ca", 5, 1001),
        _make_rag_item("cb", 5, 1002),
        _make_web_item("web1"),
    ]
    result = await svc._filter_visible_rag_items(items, login_user=None)
    assert [item.citationId for item in result] == ["ca", "cb", "web1"]


# ---------------------------------------------------------------------------
# resolve_citations integration — AC-15 / AC-16 / AC-17 wire-up
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_citations_filters_then_enriches(monkeypatch):
    """resolve_citations runs the filter before enrichment; the response
    preserves input ordering for surviving items.
    """
    svc = _make_service()
    _stub_enrich_passthrough(svc, monkeypatch)
    _stub_post_filter(monkeypatch, {5: {1001}})

    items = [
        _make_rag_item("visible", 5, 1001),
        _make_rag_item("hidden", 5, 1002),
    ]
    svc.registry_service.list_citations_by_ids = AsyncMock(return_value=items)
    svc.runtime_cache_service.get_citations_by_ids = AsyncMock(return_value=[])

    login_user = MagicMock(user_id=7)
    login_user.is_admin = MagicMock(return_value=False)

    result = await svc.resolve_citations(citation_ids=["visible", "hidden"], login_user=login_user)

    assert [item.citationId for item in result] == ["visible"]


# ---------------------------------------------------------------------------
# resolve_citation (single) — AC-18 NotFoundError on no permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_citation_single_rag_inaccessible_raises_not_found(monkeypatch):
    """Single RAG resolve for an inaccessible documentId raises NotFoundError
    instead of returning a masked payload (AC-18).
    """
    svc = _make_service()
    _stub_enrich_passthrough(svc, monkeypatch)
    _stub_post_filter(monkeypatch, {5: set()})

    item = _make_rag_item("hidden", 5, 1002)
    svc.registry_service.get_citation = AsyncMock(return_value=item)
    svc.runtime_cache_service.get_citation = AsyncMock(return_value=None)

    login_user = MagicMock(user_id=7)
    login_user.is_admin = MagicMock(return_value=False)

    with pytest.raises(NotFoundError):
        await svc.resolve_citation(citation_id="hidden", login_user=login_user)


@pytest.mark.asyncio
async def test_resolve_citation_single_web_skips_filter(monkeypatch):
    """Single web resolve does not consult the view_file filter (AC-19)."""
    svc = _make_service()
    _stub_enrich_passthrough(svc, monkeypatch)

    fga_called = False

    async def fake_post(self, space_id, file_ids):
        nonlocal fga_called
        fga_called = True
        return set()

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service."
        "KnowledgeFileVisibilityService.post_filter_visible_files",
        fake_post,
    )

    item = _make_web_item("web1")
    svc.registry_service.get_citation = AsyncMock(return_value=item)
    svc.runtime_cache_service.get_citation = AsyncMock(return_value=None)

    login_user = MagicMock(user_id=7)
    login_user.is_admin = MagicMock(return_value=False)

    result = await svc.resolve_citation(citation_id="web1", login_user=login_user)
    assert result.citationId == "web1"
    assert fga_called is False


@pytest.mark.asyncio
async def test_resolve_citation_anonymous_caller_is_refused(monkeypatch):
    """F054 overrides F029 AC-20 (release-contract table 4).

    AC-20 originally let an anonymous caller through unfiltered so share links
    kept working. That is the hole F054 closes: handing out a share link also
    handed out the knowledge files behind it, signed preview URLs included. A
    knowledge source now 404s for a caller with no logged-in user; a web source
    still resolves (see the test below).
    """
    svc = _make_service()
    _stub_enrich_passthrough(svc, monkeypatch)

    async def fake_post(self, space_id, file_ids):
        raise AssertionError("anonymous caller must not invoke FGA")

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service."
        "KnowledgeFileVisibilityService.post_filter_visible_files",
        fake_post,
    )

    item = _make_rag_item("rag1", 5, 1001)
    svc.registry_service.get_citation = AsyncMock(return_value=item)
    svc.runtime_cache_service.get_citation = AsyncMock(return_value=None)

    with pytest.raises(NotFoundError):
        await svc.resolve_citation(citation_id="rag1", login_user=None)


@pytest.mark.asyncio
async def test_resolve_citation_anonymous_caller_still_gets_web_sources(monkeypatch):
    """Public URLs holding no tenant data stay readable without a login, so
    share-page web badges keep working (F054)."""
    svc = _make_service()
    _stub_enrich_passthrough(svc, monkeypatch)

    item = CitationRegistryItemSchema(
        citationId="web1",
        type=CitationType.WEB,
        sourcePayload=WebCitationPayloadSchema(url="https://example.com/a"),
    )
    svc.registry_service.get_citation = AsyncMock(return_value=item)
    svc.runtime_cache_service.get_citation = AsyncMock(return_value=None)

    result = await svc.resolve_citation(citation_id="web1", login_user=None)
    assert result.citationId == "web1"
