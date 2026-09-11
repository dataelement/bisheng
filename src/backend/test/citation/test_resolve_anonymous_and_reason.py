"""F054 T003 — anonymous tightening + why a citation failed to resolve.

Two changes to CitationResolveService, both RED until T006/T011 land.

**Anonymous tightening.** F029 AC-20 deliberately let anonymous callers through
unfiltered so share links kept working, and F041's tiering passed everything
when ``permitted is None``. That is the hole this feature closes: a share link
handed out today also hands out the knowledge files behind it, signed preview
URLs included. From now on a call carrying no logged-in user gets no knowledge
and no article sources at all — ``shared``-tier included, since that tier is
about *which logged-in user* may open the file, not about anonymity. Web
citations still resolve: they are public URLs holding no tenant data, and
blacking them out would break share-page badges for no security gain.
**This overrides F029 AC-20** (release-contract table 4).

**Reason reporting.** The batch endpoint used to just omit whatever it could
not resolve, so the front-end could not tell "you may not see this" from "this
source is gone" and showed one vague failure for both. Resolve now reports a
reason per unresolved id, decided in this order (design §3 decision 5) — the
order is a safety property, not a preference:

  1. no logged-in user            → forbidden  (never leak existence)
  2. no record in cache or DB     → expired    (nothing is known to leak)
  3. record exists, view_file says no → forbidden
  4. record exists, permitted, underlying file gone → expired (past the gate)

Rule 1 before rule 2 is what stops an anonymous caller from probing which
citation ids ever existed.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.citation.domain.schemas.citation_schema import (
    ArticleCitationPayloadSchema,
    CitationRegistryItemSchema,
    CitationType,
    RagCitationItemSchema,
    RagCitationPayloadSchema,
    WebCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_resolve_service import CitationResolveService
from bisheng.common.errcode.http_error import NotFoundError

FORBIDDEN = "forbidden"
EXPIRED = "expired"


def _rag(citation_id: str, document_id: int = 7, access_scope: str = "per_user") -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.RAG,
        accessScope=access_scope,
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=1,
            documentId=document_id,
            documentName=f"file-{document_id}.pdf",
            snippet="片段",
            items=[RagCitationItemSchema(itemId="0", content="chunk")],
        ),
    )


def _web(citation_id: str = "websearch_ff001122") -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.WEB,
        sourcePayload=WebCitationPayloadSchema(url="https://example.com/a", title="标题"),
    )


def _article(citation_id: str = "articlesearch_ab12cd34") -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.ARTICLE,
        sourcePayload=ArticleCitationPayloadSchema(
            articleDocId="doc-9", title="文章标题", sourceUrl="https://example.com/post"
        ),
    )


def _service(cached: list[CitationRegistryItemSchema], stored: list[CitationRegistryItemSchema] | None = None):
    """Service whose runtime cache returns ``cached`` and whose DB returns ``stored``."""
    repository = MagicMock()
    service = CitationResolveService(repository, runtime_cache_service=MagicMock())
    service.runtime_cache_service.get_citations_by_ids = AsyncMock(return_value=list(cached))
    service.runtime_cache_service.get_citation = AsyncMock(return_value=cached[0] if cached else None)
    service.registry_service.list_citations_by_ids = AsyncMock(return_value=list(stored or []))
    service.registry_service.get_citation = AsyncMock(return_value=(stored or [None])[0])
    return service


def _logged_in(service) -> MagicMock:
    """A logged-in caller for tests that are about the reason rules.

    The COFCO line puts a file-change layer in front of tiering: locations are
    re-read from the knowledge file table and anything hidden by a pending
    change is denied. That layer needs a real tenant on the identity and in the
    ContextVar, which these tests have no reason to build. It is stubbed to a
    pass-through so each test still exercises the rule it is named after.
    """
    service._canonicalize_rag_items = AsyncMock(side_effect=lambda items, _user: list(items))
    service._project_old_file_names = AsyncMock(side_effect=lambda items, _user: list(items))
    service._file_change_visible_ids = AsyncMock(return_value=None)
    return MagicMock()


def _reasons(result) -> dict[str, str]:
    return {entry.citationId: entry.reason for entry in result.unresolved}


# --------------------------------------------------------------------------- #
# Anonymous tightening — AC-14
# --------------------------------------------------------------------------- #


async def test_anonymous_gets_no_knowledge_source():
    item = _rag("knowledgesearch_ab12cd34")
    service = _service([item])

    result = await service.resolve_citations_with_reasons([item.citationId], login_user=None)

    assert result.items == []
    assert _reasons(result) == {item.citationId: FORBIDDEN}


async def test_anonymous_gets_no_shared_tier_knowledge_source_either():
    """The shared tier answers 'which logged-in user may open the file'. With no
    logged-in user there is no one to answer for, so it is refused like the rest
    — this is the F041 leak the feature closes."""
    item = _rag("knowledgesearch_deadbeef", access_scope="shared")
    service = _service([item])

    result = await service.resolve_citations_with_reasons([item.citationId], login_user=None)

    assert result.items == []
    assert _reasons(result) == {item.citationId: FORBIDDEN}


async def test_anonymous_gets_no_article_source():
    item = _article()
    service = _service([item])

    result = await service.resolve_citations_with_reasons([item.citationId], login_user=None)

    assert result.items == []
    assert _reasons(result) == {item.citationId: FORBIDDEN}


async def test_anonymous_still_gets_web_sources():
    """Public URLs, no tenant data. Blacking these out would strip share-page
    badges for no security gain."""
    item = _web()
    service = _service([item])

    result = await service.resolve_citations_with_reasons([item.citationId], login_user=None)

    assert [i.citationId for i in result.items] == [item.citationId]
    assert result.unresolved == []


async def test_anonymous_mixed_batch_keeps_only_the_web_source():
    rag, article, web = _rag("knowledgesearch_ab12cd34"), _article(), _web()
    service = _service([rag, article, web])

    result = await service.resolve_citations_with_reasons(
        [rag.citationId, article.citationId, web.citationId], login_user=None
    )

    assert [i.citationId for i in result.items] == [web.citationId]
    assert _reasons(result) == {rag.citationId: FORBIDDEN, article.citationId: FORBIDDEN}


async def test_anonymous_single_resolve_of_a_knowledge_source_is_not_found():
    item = _rag("knowledgesearch_ab12cd34")
    service = _service([item])

    with pytest.raises(NotFoundError):
        await service.resolve_citation(item.citationId, login_user=None)


# --------------------------------------------------------------------------- #
# Reason ordering — AC-08, AC-09, AC-10
# --------------------------------------------------------------------------- #


async def test_unknown_citation_id_reports_expired():
    """Rule 2: neither cache nor DB knows it. Nothing about it can leak, so the
    reader is told the source is gone rather than that they lack permission."""
    service = _service([], stored=[])

    result = await service.resolve_citations_with_reasons(["knowledgesearch_00000000"], login_user=MagicMock())

    assert result.items == []
    assert _reasons(result) == {"knowledgesearch_00000000": EXPIRED}


async def test_unknown_citation_id_still_reports_forbidden_when_anonymous():
    """Rule 1 outranks rule 2 (AC-10). Otherwise an anonymous caller could probe
    which citation ids ever existed by watching the reason flip."""
    service = _service([], stored=[])

    result = await service.resolve_citations_with_reasons(["knowledgesearch_00000000"], login_user=None)

    assert _reasons(result) == {"knowledgesearch_00000000": FORBIDDEN}


async def test_logged_in_user_without_view_file_gets_forbidden():
    """Rule 3."""
    item = _rag("knowledgesearch_ab12cd34", document_id=7)
    service = _service([item])
    service._permitted_file_ids = AsyncMock(return_value=set())

    result = await service.resolve_citations_with_reasons([item.citationId], login_user=_logged_in(service))

    assert result.items == []
    assert _reasons(result) == {item.citationId: FORBIDDEN}


async def test_permitted_user_whose_file_was_deleted_gets_expired():
    """Rule 4: already past the permission gate, so naming the source as gone
    leaks nothing."""
    item = _rag("knowledgesearch_ab12cd34", document_id=7)
    service = _service([item])
    service._permitted_file_ids = AsyncMock(return_value={7})
    service._enrich_item = AsyncMock(side_effect=NotFoundError())

    result = await service.resolve_citations_with_reasons([item.citationId], login_user=_logged_in(service))

    assert result.items == []
    assert _reasons(result) == {item.citationId: EXPIRED}


# --------------------------------------------------------------------------- #
# INV-7 does not move for logged-in users — AC-13
# --------------------------------------------------------------------------- #


async def test_logged_in_tiering_is_unchanged():
    """per_user without view_file is dropped; shared survives; web passes. This
    is F029/F041 behaviour verbatim — the tightening must not reach it."""
    service = _service([])
    per_user_denied = _rag("knowledgesearch_denied", document_id=1)
    shared_denied = _rag("knowledgesearch_shared", document_id=2, access_scope="shared")
    per_user_allowed = _rag("knowledgesearch_allowed", document_id=3)
    web = _web()

    kept = service._apply_tier_filter([per_user_denied, shared_denied, per_user_allowed, web], {3})

    assert {i.citationId for i in kept} == {"knowledgesearch_shared", "knowledgesearch_allowed", web.citationId}


async def test_resolved_items_keep_their_request_order():
    """Ordering is part of the existing contract: the front-end numbers badges
    by first appearance and relies on it."""
    a, b = _web("websearch_aaaa1111"), _web("websearch_bbbb2222")
    service = _service([b, a])

    result = await service.resolve_citations_with_reasons([a.citationId, b.citationId], login_user=None)

    assert [i.citationId for i in result.items] == [a.citationId, b.citationId]
