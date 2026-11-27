"""DocFlow's stored one-based coordinates must reach the shared viewer zero-based."""

import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationItemSchema,
    RagCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
from bisheng.citation.domain.services.citation_resolve_service import CitationResolveService
from bisheng.knowledge.rag.pipeline.loader.docflow import DocFlowLoader
from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer
from bisheng.workflow.nodes.input.const import InputFileMetadata


def _bbox(page, base=None):
    value = {"chunk_bboxes": [{"page": page, "bbox": [0, 0, 60, 20]}]}
    if base is not None:
        value["page_base"] = base
    return json.dumps(value)


def test_docflow_loader_to_temp_citation_preserves_first_and_last_pages(tmp_path, monkeypatch):
    """The temporary-input whitelist must not discard the source page convention."""
    import fitz

    path = tmp_path / "two-pages.pdf"
    with fitz.open() as pdf:
        pdf.new_page(width=200, height=100)
        pdf.new_page(width=200, height=100)
        pdf.save(path)
    results = [
        {
            "total_page_num": 2,
            "document": {
                "pages": [
                    {"width": 200, "height": 100, "lines": [{"text": text, "position": [0, 0, 60, 20]}]}
                    for text in ("first", "last")
                ]
            },
        }
    ]
    state_module = ModuleType("bisheng.knowledge.domain.services.docflow_state")
    state_module.DocFlowState = lambda tenant: object()
    service_module = ModuleType("bisheng.knowledge.domain.services.docflow_service")
    service_module.DocFlowService = lambda config, state: SimpleNamespace(
        parse=lambda source: results, client=SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setitem(sys.modules, state_module.__name__, state_module)
    monkeypatch.setitem(sys.modules, service_module.__name__, service_module)
    monkeypatch.setattr("bisheng.core.context.tenant.get_current_tenant_id", lambda: 1)
    loader = DocFlowLoader(file_path=str(path), file_extension="pdf", file_metadata={}, tmp_dir=str(tmp_path))
    documents = loader.load()
    # Stored OCR/preview coordinates retain the existing customer contract.
    assert documents[0].metadata["pages"] == [1, 2]
    assert [box.page for box in loader.bbox_list] == [1, 2]
    chunks = SplitterTransformer(
        chunk_size=5, chunk_overlap=0, separator=["\n\n", ""], separator_rule=["after", "after"]
    ).transform_documents(documents)
    whitelist = {field.field_name for field in InputFileMetadata}
    for chunk in chunks:
        chunk.metadata = {key: value for key, value in chunk.metadata.items() if key in whitelist}
        chunk.metadata.update(document_id="temp-file", document_name="two-pages.pdf")
    items = [
        item for entry in CitationRegistryService.build_temp_registry(chunks) for item in entry.sourcePayload.items
    ]
    assert [item.page for item in items] == [0, 1]
    assert [box["page"] for item in items for box in json.loads(item.bbox)["chunk_bboxes"]] == [0, 1]
    assert all(json.loads(item.bbox)["page_base"] == 0 for item in items)


@pytest.mark.parametrize("kind", ["rag", "temp"])
def test_explicit_page_base_is_normalized_once_in_registry(kind):
    document = Document(
        page_content="last page",
        metadata={
            "document_id": 12 if kind == "rag" else "temp-file",
            "chunk_index": 0,
            "page": 2,
            "bbox": _bbox(2, 1),
        },
    )
    build = (
        CitationRegistryService._build_rag_chunk_item
        if kind == "rag"
        else CitationRegistryService._build_temp_chunk_item
    )
    first = build(document)
    assert first.page == 1
    assert json.loads(first.bbox) == {"chunk_bboxes": [{"page": 1, "bbox": [0, 0, 60, 20]}], "page_base": 0}
    document.metadata.update(page=first.page, bbox=first.bbox)
    second = build(document)
    assert second.page == 1
    assert second.bbox == first.bbox


def test_unlabelled_historical_temp_coordinates_are_not_guessed():
    item = CitationRegistryService._build_temp_chunk_item(
        Document(page_content="unknown provider", metadata={"document_id": "old-temp", "page": 2, "bbox": _bbox(2)})
    )
    assert item.page == 2
    assert json.loads(item.bbox)["chunk_bboxes"][0]["page"] == 2


@pytest.mark.parametrize("base,stored_page,expected", [(None, 1, 0), (None, 2, 1), (0, 1, 1)])
@pytest.mark.parametrize("url_allowed", [True, False])
async def test_resolve_historical_docflow_rag_and_repeated_resolve(
    monkeypatch, base, stored_page, expected, url_allowed
):
    file = SimpleNamespace(id=12, knowledge_id=3, file_name="stored.pdf", parse_type="docflow")
    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_resolve_service.KnowledgeFileDao.query_by_id_sync", lambda _: file
    )
    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_resolve_service.KnowledgeService.get_file_share_url",
        lambda *a: ("download", "preview"),
    )
    service = CitationResolveService(MagicMock(), runtime_cache_service=MagicMock())
    original = CitationRegistryItemSchema(
        citationId="rag-1",
        type=CitationType.RAG,
        sourcePayload=RagCitationPayloadSchema(
            documentId=12,
            items=[
                RagCitationItemSchema(itemId="a", page=stored_page, bbox=_bbox(stored_page, base)),
                RagCitationItemSchema(itemId="b", page=stored_page, bbox=_bbox(stored_page, base)),
            ],
        ),
    )
    first = await service._enrich_rag_item(original, None, url_allowed=url_allowed)
    second = await service._enrich_rag_item(first, None, url_allowed=url_allowed)
    for result in (first, second):
        assert [item.page for item in result.sourcePayload.items] == [expected, expected]
        assert all(json.loads(item.bbox)["chunk_bboxes"][0]["page"] == expected for item in result.sourcePayload.items)
    # Enrichment must not mutate the persisted/runtime-cache source object.
    assert original.sourcePayload.items[0].page == stored_page
    if not url_allowed:
        assert first.sourcePayload.downloadUrl is None
        assert first.sourcePayload.previewUrl is None


async def test_docflow_file_bbox_fallback_uses_same_zero_based_convention(monkeypatch):
    file = SimpleNamespace(id=12, knowledge_id=3, file_name="stored.pdf", parse_type="docflow")
    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_resolve_service.KnowledgeFileDao.query_by_id_sync", lambda _: file
    )
    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_resolve_service.KnowledgeService.get_file_share_url",
        lambda *a: ("download", "preview"),
    )
    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_resolve_service.KnowledgeService.get_file_bbox",
        lambda *a: {
            "1-0-0-60-20": {"page": 1, "bbox": [0, 0, 60, 20]},
            "2-0-0-60-20": {"page": 2, "bbox": [0, 0, 60, 20]},
        },
    )
    service = CitationResolveService(MagicMock(), runtime_cache_service=MagicMock())
    result = await service._enrich_rag_item(
        CitationRegistryItemSchema(
            citationId="rag-1",
            type=CitationType.RAG,
            sourcePayload=RagCitationPayloadSchema(documentId=12, items=[RagCitationItemSchema(itemId="a", page=1)]),
        ),
        None,
    )
    item = result.sourcePayload.items[0]
    assert item.page == 0
    assert [box["page"] for box in json.loads(item.bbox)["chunk_bboxes"]] == [0, 1]


async def test_other_provider_rag_page_zero_is_unchanged(monkeypatch):
    file = SimpleNamespace(id=12, knowledge_id=3, file_name="stored.pdf", parse_type="etl4lm")
    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_resolve_service.KnowledgeFileDao.query_by_id_sync", lambda _: file
    )
    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_resolve_service.KnowledgeService.get_file_share_url",
        lambda *a: ("download", "preview"),
    )
    service = CitationResolveService(MagicMock(), runtime_cache_service=MagicMock())
    result = await service._enrich_rag_item(
        CitationRegistryItemSchema(
            citationId="rag-1",
            type=CitationType.RAG,
            sourcePayload=RagCitationPayloadSchema(
                documentId=12, items=[RagCitationItemSchema(itemId="a", page=0, bbox=_bbox(0))]
            ),
        ),
        None,
    )
    assert result.sourcePayload.items[0].page == 0
    assert json.loads(result.sourcePayload.items[0].bbox)["chunk_bboxes"][0]["page"] == 0


async def test_docflow_page_without_boxes_is_normalized_and_stamped(monkeypatch):
    file = SimpleNamespace(id=12, knowledge_id=3, file_name="stored.pdf", parse_type="docflow")
    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_resolve_service.KnowledgeFileDao.query_by_id_sync", lambda _: file
    )
    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_resolve_service.KnowledgeService.get_file_share_url",
        lambda *a: ("download", "preview"),
    )
    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_resolve_service.KnowledgeService.get_file_bbox", lambda *a: None
    )
    service = CitationResolveService(MagicMock(), runtime_cache_service=MagicMock())
    item = CitationRegistryItemSchema(
        citationId="rag-1",
        type=CitationType.RAG,
        sourcePayload=RagCitationPayloadSchema(documentId=12, items=[RagCitationItemSchema(itemId="a", page=1)]),
    )
    first = await service._enrich_rag_item(item, None)
    second = await service._enrich_rag_item(first, None)
    assert first.sourcePayload.items[0].page == second.sourcePayload.items[0].page == 0
    assert json.loads(first.sourcePayload.items[0].bbox) == {"page_base": 0}
