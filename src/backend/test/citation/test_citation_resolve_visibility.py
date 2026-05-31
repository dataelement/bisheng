"""F026 tests for CitationResolveService view_file filtering.

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
- AC-20: anonymous caller (``login_user is None``) preserves the legacy
  behaviour — no filtering applied.
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

    async def fake_enrich(item, login_user):  # noqa: ARG001
        return item

    monkeypatch.setattr(svc, "_enrich_item", fake_enrich)


def _stub_post_filter(monkeypatch, allowed_by_space: dict[int, set[int]]):
    """Patch KnowledgeFileVisibilityService.post_filter_visible_files."""

    async def fake_post(self, space_id, file_ids):  # noqa: ARG001
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
    """login_user=None → no filtering, items unchanged (AC-20)."""
    svc = _make_service()

    async def fake_post(self, space_id, file_ids):  # noqa: ARG001
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

    result = await svc.resolve_citations(
        citation_ids=["visible", "hidden"], login_user=login_user
    )

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

    async def fake_post(self, space_id, file_ids):  # noqa: ARG001
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
async def test_resolve_citation_anonymous_caller_passthrough(monkeypatch):
    """Anonymous caller (login_user=None) returns the enriched item without filtering."""
    svc = _make_service()
    _stub_enrich_passthrough(svc, monkeypatch)

    async def fake_post(self, space_id, file_ids):  # noqa: ARG001
        raise AssertionError("anonymous caller must not invoke FGA")

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service."
        "KnowledgeFileVisibilityService.post_filter_visible_files",
        fake_post,
    )

    item = _make_rag_item("rag1", 5, 1001)
    svc.registry_service.get_citation = AsyncMock(return_value=item)
    svc.runtime_cache_service.get_citation = AsyncMock(return_value=None)

    result = await svc.resolve_citation(citation_id="rag1", login_user=None)
    assert result.citationId == "rag1"
