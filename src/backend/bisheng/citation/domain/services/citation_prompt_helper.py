from collections import defaultdict, deque
from typing import Any, Deque, Dict, List

from langchain_core.documents import Document

from bisheng.citation.domain.schemas.citation_schema import CitationRegistryItemSchema
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
from bisheng.core.prompts.prompt_loader import PromptLoader


def _load_citation_prompt_rules() -> str:
    try:
        prompt_loader = PromptLoader()
        prompt_obj = prompt_loader.render_prompt('citation', 'citation_rules')
        return str(prompt_obj.prompt).strip()
    except Exception as e:
        return (f"Failed to load citation prompt rules: {e}. "
                "Please ensure the prompt file 'citation_rules' exists in the 'citation' category and is properly formatted.")


CITATION_PROMPT_RULES = _load_citation_prompt_rules()


def _rag_registry_signature(item: CitationRegistryItemSchema) -> tuple[Any, ...]:
    payload = item.sourcePayload
    chunk_item = payload.items[0] if payload.items else None
    return (
        payload.documentId,
        chunk_item.chunkId if chunk_item else None,
        chunk_item.chunkIndex if chunk_item else None,
        chunk_item.content if chunk_item else payload.snippet,
    )


def _rag_document_signature(document: Document) -> tuple[Any, ...]:
    metadata = CitationRegistryService._parse_metadata(document)
    chunk_item = CitationRegistryService._build_rag_chunk_item(document)
    document_id = CitationRegistryService._parse_optional_int(
        metadata.get('document_id') or metadata.get('file_id')
    )
    return (
        document_id,
        chunk_item.chunkId,
        chunk_item.chunkIndex,
        chunk_item.content,
    )


def _build_rag_key_map(
        documents: List[Document],
        registry_items: List[CitationRegistryItemSchema],
) -> Dict[int, str]:
    key_map: Dict[int, str] = {}
    registry_by_signature: Dict[tuple[Any, ...], Deque[str]] = defaultdict(deque)
    fallback_keys = deque(item.key for item in registry_items if item.key)

    for item in registry_items:
        if item.key:
            registry_by_signature[_rag_registry_signature(item)].append(item.key)

    for index, document in enumerate(documents):
        signature = _rag_document_signature(document)
        if registry_by_signature[signature]:
            key_map[index] = registry_by_signature[signature].popleft()
        elif fallback_keys:
            key_map[index] = fallback_keys.popleft()
    return key_map


def _is_citable_rag_document(document: Document) -> bool:
    metadata = document.metadata or {}
    return bool(metadata)


def annotate_rag_documents_with_citations(documents: List[Document]) -> List[Document]:
    """Append citation keys to RAG documents before prompt formatting."""
    if not documents:
        return documents

    indexed_citable_documents = [
        (index, document)
        for index, document in enumerate(documents)
        if _is_citable_rag_document(document)
    ]
    citable_documents = [document for _, document in indexed_citable_documents]
    registry_items = CitationRegistryService.build_rag_registry(citable_documents)
    citable_key_map = _build_rag_key_map(citable_documents, registry_items)
    key_map = {
        original_index: citable_key_map[citable_index]
        for citable_index, (original_index, _) in enumerate(indexed_citable_documents)
        if citable_index in citable_key_map
    }
    annotated_documents: List[Document] = []
    for index, document in enumerate(documents):
        citation_key = key_map.get(index)
        metadata = dict(document.metadata or {})
        page_content = document.page_content or ''
        if citation_key:
            metadata['citation_key'] = citation_key
            page_content = f'{page_content}\n\ncitation_key: {citation_key}'
        annotated_documents.append(Document(page_content=page_content, metadata=metadata))

    return annotated_documents


def annotate_web_results_with_citations(results: List[dict]) -> List[dict]:
    """Append citation keys to web search results before returning tool output."""
    if not results or not isinstance(results, list):
        return results

    registry_items = CitationRegistryService.build_web_registry(results)
    key_by_url_item_id = {
        (item.sourcePayload.url, item.itemId): item.key
        for item in registry_items
        if item.sourcePayload.url and item.itemId and item.key
    }

    annotated_results: List[dict] = []
    fallback_indexes_by_url: Dict[str, int] = defaultdict(int)
    for result in results:
        annotated_result = dict(result)
        raw_url = CitationRegistryService._parse_optional_text(result.get('url') or result.get('link')) or ''
        normalized_url = CitationRegistryService.normalize_url(raw_url)
        item_id = str(result.get('itemId') or result.get('snippetId') or result.get('id') or '')
        if not item_id:
            item_id = f'item:{fallback_indexes_by_url[normalized_url]}'
        fallback_indexes_by_url[normalized_url] += 1
        citation_key = key_by_url_item_id.get((normalized_url, item_id))
        if citation_key:
            annotated_result['citation_key'] = citation_key
        annotated_results.append(annotated_result)
    return annotated_results
