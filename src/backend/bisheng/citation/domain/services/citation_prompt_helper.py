import re
from collections import OrderedDict, defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Set

from langchain_core.documents import Document

from bisheng.citation.domain.repositories.implementations.message_citation_repository_impl import (
    MessageCitationRepositoryImpl,
)
from bisheng.citation.domain.schemas.citation_schema import CitationRegistryItemSchema
from bisheng.citation.domain.services.citation_runtime_cache_service import (
    CitationRuntimeCacheService,
)
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.core.prompts.prompt_loader import PromptLoader

CITATION_START_MARKER = '\ue200'
CITATION_SEPARATOR_MARKER = '\ue201'
CITATION_END_MARKER = '\ue202'
CITATION_KEY_PATTERN = re.compile(
    rf'{CITATION_START_MARKER}(.*?){CITATION_END_MARKER}',
    re.DOTALL,
)


class CitationRegistryCollector:
    """Collect citation registry items across copied tool instances."""

    def __init__(self) -> None:
        self.items: List[CitationRegistryItemSchema] = []

    def clear(self) -> None:
        self.items.clear()

    def extend(self, items: List[CitationRegistryItemSchema]) -> None:
        self.items.extend(items)

    def list_items(self) -> List[CitationRegistryItemSchema]:
        return list(self.items)


def _load_citation_prompt_rules() -> str:
    try:
        prompt_loader = PromptLoader()
        prompt_obj = prompt_loader.render_prompt('citation', 'citation_rules')
        return str(prompt_obj.prompt).strip()
    except Exception as e:
        return (f"Failed to load citation prompt rules: {e}. "
                "Please ensure the prompt file 'citation_rules' exists in the 'citation' category and is properly formatted.")


CITATION_PROMPT_RULES = _load_citation_prompt_rules()
_citation_runtime_cache_service = CitationRuntimeCacheService()


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


def _split_citation_key(citation_key: Any) -> tuple[Optional[str], Optional[str]]:
    if not isinstance(citation_key, str):
        return None, None
    if ':' not in citation_key:
        return None, None
    citation_id, item_id = citation_key.split(':', 1)
    if not citation_id or not item_id:
        return None, None
    return citation_id, item_id


def _clean_document_for_citation(document: Document) -> Document:
    metadata = dict(document.metadata or {})
    citation_key = metadata.pop('citation_key', None)
    page_content = document.page_content or ''
    if citation_key:
        page_content = page_content.replace(f'\n\ncitation_key: {citation_key}', '')
    return Document(page_content=page_content, metadata=metadata)


def collect_rag_citation_registry_items(documents: List[Document]) -> List[CitationRegistryItemSchema]:
    """Collect persistence-ready citation items from annotated RAG documents."""
    if not documents:
        return []

    grouped_documents: "OrderedDict[str, List[Document]]" = OrderedDict()
    for document in documents:
        citation_id, _ = _split_citation_key((document.metadata or {}).get('citation_key'))
        if not citation_id:
            continue
        grouped_documents.setdefault(citation_id, []).append(_clean_document_for_citation(document))

    registry_items: List[CitationRegistryItemSchema] = []
    knowledge_names = CitationRegistryService._load_knowledge_names([
        document
        for grouped_docs in grouped_documents.values()
        for document in grouped_docs
    ])
    for citation_id, grouped_docs in grouped_documents.items():
        payload = CitationRegistryService._build_rag_payload_with_knowledge_names(grouped_docs, knowledge_names)
        registry_items.extend(CitationRegistryService._flatten_rag_payload(citation_id, payload))
    return registry_items


def collect_web_citation_registry_items(results: List[dict]) -> List[CitationRegistryItemSchema]:
    """Collect persistence-ready citation items from annotated web search results."""
    if not results or not isinstance(results, list):
        return []

    grouped_results: "OrderedDict[str, List[dict]]" = OrderedDict()
    for result in results:
        if not isinstance(result, dict):
            continue
        citation_id, _ = _split_citation_key(result.get('citation_key'))
        if not citation_id:
            continue
        result_without_citation = dict(result)
        result_without_citation.pop('citation_key', None)
        grouped_results.setdefault(citation_id, []).append(result_without_citation)

    registry_items: List[CitationRegistryItemSchema] = []
    for citation_id, grouped_page_results in grouped_results.items():
        first_result = grouped_page_results[0]
        raw_url = CitationRegistryService._parse_optional_text(
            first_result.get('url') or first_result.get('link')) or ''
        normalized_url = CitationRegistryService.normalize_url(raw_url)
        payload = CitationRegistryService._build_web_payload(normalized_url, grouped_page_results)
        registry_items.extend(CitationRegistryService._flatten_web_payload(citation_id, payload))
    return registry_items


def extract_citation_ids_from_text(text: str) -> Set[str]:
    """Extract citation IDs that are actually referenced in generated text."""
    if not text:
        return set()

    citation_ids: Set[str] = set()
    for marker_content in CITATION_KEY_PATTERN.findall(text):
        for citation_key in marker_content.split(CITATION_SEPARATOR_MARKER):
            citation_id, _ = _split_citation_key(citation_key.strip())
            if citation_id:
                citation_ids.add(citation_id)
    return citation_ids


def filter_registry_items_by_text(
        items: List[CitationRegistryItemSchema],
        text: str,
) -> List[CitationRegistryItemSchema]:
    """Keep only registry items referenced by the generated answer."""
    citation_ids = extract_citation_ids_from_text(text)
    if not citation_ids:
        return []
    return [item for item in items if item.citationId in citation_ids]


def select_registry_items_for_persistence(
        items: List[CitationRegistryItemSchema],
        text: str,
) -> List[CitationRegistryItemSchema]:
    """Prefer answer-referenced citations, and keep generated citations when no marker exists."""
    if not items:
        return []

    citation_ids = extract_citation_ids_from_text(text)
    if not citation_ids:
        return items

    return [item for item in items if item.citationId in citation_ids]


async def cache_citation_registry_items(
        items: List[CitationRegistryItemSchema],
) -> List[CitationRegistryItemSchema]:
    if not items:
        return []
    return await _citation_runtime_cache_service.save_citations(items)


def cache_citation_registry_items_sync(
        items: List[CitationRegistryItemSchema],
) -> List[CitationRegistryItemSchema]:
    if not items:
        return []
    return _citation_runtime_cache_service.save_citations_sync(items)


def save_message_citations_sync(
        message_id: int | str | None,
        items: List[CitationRegistryItemSchema],
        chat_id: Optional[str] = None,
        flow_id: Optional[str] = None,
) -> None:
    """Persist citation registry items for a saved chat message."""
    if not message_id or not items:
        if items:
            cache_citation_registry_items_sync(items)
        return

    if not isinstance(message_id, int):
        cache_citation_registry_items_sync(items)
        return

    with get_sync_db_session() as session:
        repository = MessageCitationRepositoryImpl(session)
        service = CitationRegistryService(repository)
        service.save_citations_sync(
            message_id=message_id,
            items=items,
            chat_id=chat_id,
            flow_id=flow_id,
        )
    cache_citation_registry_items_sync(items)


async def save_message_citations(
        message_id: int | str | None,
        items: List[CitationRegistryItemSchema],
        chat_id: Optional[str] = None,
        flow_id: Optional[str] = None,
) -> None:
    """Persist citation registry items for a saved chat message asynchronously."""
    if not message_id or not items:
        if items:
            await cache_citation_registry_items(items)
        return

    if not isinstance(message_id, int):
        await cache_citation_registry_items(items)
        return

    async with get_async_db_session() as session:
        repository = MessageCitationRepositoryImpl(session)
        service = CitationRegistryService(repository)
        await service.save_citations(
            message_id=message_id,
            items=items,
            chat_id=chat_id,
            flow_id=flow_id,
        )
    await cache_citation_registry_items(items)
