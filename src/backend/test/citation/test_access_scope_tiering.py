"""F041 T009 — citation resolve tiering by accessScope (per_user vs shared).

per_user RAG citations without view_file are dropped (F029, AC-20); shared
(toggle-OFF knowledge-space) citations survive with source metadata but their
full-file preview/download URLs are gated by the viewer's view_file (AC-21/22).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationItemSchema,
    RagCitationPayloadSchema,
    WebCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_resolve_service import CitationResolveService


def _rag(citation_id: str, doc_id: int, access_scope: str = "per_user") -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.RAG,
        accessScope=access_scope,
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=9,
            documentId=doc_id,
            documentName=f"file-{doc_id}.pdf",
            items=[RagCitationItemSchema(itemId="0", content="chunk")],
        ),
    )


def _web(citation_id: str) -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id, type=CitationType.WEB, sourcePayload=WebCitationPayloadSchema(url="http://x")
    )


def _svc() -> CitationResolveService:
    return CitationResolveService(MagicMock(), runtime_cache_service=MagicMock())


def test_filter_tiering():
    """AC-20/21: per_user unauthorized dropped; shared kept; web kept; anon keeps all."""
    svc = _svc()
    per_user_no, shared_no, per_user_yes, web = _rag("a", 1), _rag("b", 2, "shared"), _rag("c", 3), _web("w")
    permitted = {3}  # only doc 3 has view_file
    kept = {i.citationId for i in svc._apply_tier_filter([per_user_no, shared_no, per_user_yes, web], permitted)}
    assert kept == {"b", "c", "w"}  # per_user doc1 dropped; shared doc2 kept; per_user doc3 kept; web kept
    # Anonymous (permitted=None) → no gating, everything kept.
    assert len(svc._apply_tier_filter([per_user_no], None)) == 1


def test_url_allowed():
    svc = _svc()
    assert svc._rag_url_allowed(_rag("c", 3), {3}) is True
    assert svc._rag_url_allowed(_rag("b", 2, "shared"), {3}) is False  # shared but no view_file → no URL
    assert svc._rag_url_allowed(_web("w"), {3}) is True  # web always
    assert svc._rag_url_allowed(_rag("a", 1), None) is True  # anon always


async def test_resolve_citations_shared_metadata_no_url():
    """AC-21/22: shared+no view_file → metadata but no URL; per_user+view_file → full URL."""
    svc = _svc()
    shared_no, per_user_yes = _rag("b", 2, "shared"), _rag("c", 3)
    svc.runtime_cache_service.get_citations_by_ids = AsyncMock(return_value=[shared_no, per_user_yes])

    file_infos = {
        2: SimpleNamespace(id=2, knowledge_id=9, file_name="file-2.pdf"),
        3: SimpleNamespace(id=3, knowledge_id=9, file_name="file-3.pdf"),
    }

    login_user = SimpleNamespace(user_id=7, is_admin=lambda: False)
    with (
        patch.object(svc, "_permitted_file_ids", AsyncMock(return_value={3})),  # only doc 3 visible
        patch(
            "bisheng.citation.domain.services.citation_resolve_service.KnowledgeFileDao.query_by_id_sync",
            side_effect=lambda fid: file_infos.get(fid),
        ),
        patch(
            "bisheng.citation.domain.services.citation_resolve_service.KnowledgeService.get_file_share_url",
            return_value=("http://dl", "http://pv"),
        ) as share_url,
        patch(
            "bisheng.citation.domain.services.citation_resolve_service.KnowledgeService.get_file_bbox",
            return_value=None,
        ),
    ):
        result = await svc.resolve_citations(["b", "c"], login_user)

    by_id = {i.citationId: i for i in result}
    assert set(by_id) == {"b", "c"}  # shared survives, per_user(visible) survives
    # shared, no view_file → source metadata kept, full-file URLs withheld
    assert by_id["b"].sourcePayload.documentName == "file-2.pdf"
    assert not by_id["b"].sourcePayload.downloadUrl and not by_id["b"].sourcePayload.previewUrl
    # per_user, has view_file → full URL
    assert by_id["c"].sourcePayload.downloadUrl == "http://dl"
    assert by_id["c"].sourcePayload.previewUrl == "http://pv"
    share_url.assert_called_once()  # only the URL-allowed item hit the share-url builder
