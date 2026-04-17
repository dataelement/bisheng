import json
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from langchain.docstore.document import Document

from bisheng.citation.domain.models.message_citation import MessageCitation
from bisheng.citation.domain.repositories.interfaces.message_citation_repository import MessageCitationRepository
from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationItemSchema,
    RagCitationPayloadSchema,
    WebCitationItemSchema,
    WebCitationPayloadSchema,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao


class CitationRegistryService:
    """Build and persist normalized citation registry items."""

    RAG_PREFIX = 'knowledgesearch_'
    WEB_PREFIX = 'websearch_'
    ID_SUFFIX_LENGTH = 8

    def __init__(self, repository: MessageCitationRepository):
        self.repository = repository

    @classmethod
    def generate_rag_citation_id(cls) -> str:
        """Generate a stable-format RAG citation identifier."""
        return f'{cls.RAG_PREFIX}{uuid.uuid4().hex[:cls.ID_SUFFIX_LENGTH]}'

    @classmethod
    def generate_web_citation_id(cls) -> str:
        """Generate a stable-format web citation identifier."""
        return f'{cls.WEB_PREFIX}{uuid.uuid4().hex[:cls.ID_SUFFIX_LENGTH]}'

    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalize a URL for citation identity and persistence."""
        if not url:
            return ''

        parts = urlsplit(url.strip())
        scheme = (parts.scheme or 'https').lower()
        netloc = parts.netloc.lower()
        path = parts.path or '/'
        if path != '/' and path.endswith('/'):
            path = path.rstrip('/')
        return urlunsplit((scheme, netloc, path, parts.query, ''))

    @staticmethod
    def _parse_optional_int(value: Any) -> Optional[int]:
        """Convert a loose numeric value to int when possible."""
        if value in (None, ''):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_optional_text(value: Any) -> Optional[str]:
        """Convert a loose value to string when possible."""
        if value in (None, ''):
            return None
        return str(value)

    @staticmethod
    def _dump_source_payload(payload: RagCitationPayloadSchema | WebCitationPayloadSchema) -> Dict[str, Any]:
        """Serialize source payload for persistence."""
        return payload.model_dump(exclude_none=False)

    @classmethod
    def dump_source_payload(cls, payload: RagCitationPayloadSchema | WebCitationPayloadSchema) -> Dict[str, Any]:
        """Serialize source payload for external persistence callers."""
        return cls._dump_source_payload(payload)

    @staticmethod
    def build_item_key(citation_id: str, item_id: str) -> str:
        """Build a stable flattened key for one citation item."""
        return f'{citation_id}:{item_id}'

    @staticmethod
    def _load_source_payload(citation_type: str, source_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate persisted source payload before returning it."""
        if citation_type == CitationType.RAG.value:
            return RagCitationPayloadSchema.model_validate(source_payload).model_dump(exclude_none=False)
        return WebCitationPayloadSchema.model_validate(source_payload).model_dump(exclude_none=False)

    @classmethod
    def _parse_metadata(cls, document: Document) -> Dict[str, Any]:
        """Return a normalized metadata dictionary for a retrieved document."""
        return document.metadata or {}

    @classmethod
    def _extract_rag_chunk_id(cls, metadata: Dict[str, Any]) -> Optional[str]:
        """Extract a stable chunk identifier from common retrieval metadata fields."""
        return cls._parse_optional_text(
            metadata.get('id')
            or metadata.get('chunk_id')
            or metadata.get('pk')
        )

    @classmethod
    def _extract_rag_document_name(cls, metadata: Dict[str, Any]) -> Optional[str]:
        """Extract a stable document display name from common retrieval metadata fields."""
        return cls._parse_optional_text(
            metadata.get('document_name')
            or metadata.get('file_name')
            or metadata.get('name')
            or metadata.get('source')
        )

    @classmethod
    def _extract_rag_file_type(cls, metadata: Dict[str, Any]) -> Optional[str]:
        """Extract a file type, falling back to the document name suffix when needed."""
        file_type = cls._parse_optional_text(
            metadata.get('file_type')
            or metadata.get('document_type')
            or metadata.get('suffix')
            or metadata.get('mime_type')
        )
        if file_type:
            return file_type.lstrip('.').lower()

        document_name = cls._extract_rag_document_name(metadata)
        if not document_name:
            return None

        suffix = Path(document_name).suffix
        if not suffix:
            return None
        return suffix.lstrip('.').lower() or None

    @classmethod
    def _extract_rag_bbox(cls, metadata: Dict[str, Any]) -> Optional[str]:
        """Extract bbox metadata and drop empty placeholder payloads."""
        bbox = cls._parse_optional_text(metadata.get('bbox'))
        if not bbox:
            return None

        try:
            parsed_bbox = json.loads(bbox)
        except (TypeError, ValueError):
            return bbox

        if isinstance(parsed_bbox, dict):
            normalized_bbox = {
                key: value
                for key, value in parsed_bbox.items()
                if value not in (None, '', [], {})
            }
            if not normalized_bbox:
                return None
            return json.dumps(normalized_bbox, ensure_ascii=False)

        if parsed_bbox in (None, '', [], {}):
            return None
        return bbox

    @classmethod
    def _build_rag_chunk_item(cls, document: Document) -> RagCitationItemSchema:
        """Build a grouped chunk payload item from a retrieved document."""
        metadata = cls._parse_metadata(document)
        chunk_id = cls._extract_rag_chunk_id(metadata)
        chunk_index = cls._parse_optional_int(metadata.get('chunk_index'))
        if chunk_index is not None:
            item_id = str(chunk_index)
        elif chunk_id:
            item_id = chunk_id
        else:
            item_id = str(uuid.uuid4())
        return RagCitationItemSchema(
            itemId=item_id,
            chunkId=chunk_id,
            chunkIndex=chunk_index,
            content=document.page_content or None,
            bbox=cls._extract_rag_bbox(metadata),
            page=cls._parse_optional_int(metadata.get('page')),
        )

    @classmethod
    def _build_rag_grouping_key(cls, document: Document, index: int) -> str:
        """Build a grouping key that avoids merging unrelated documents."""
        metadata = cls._parse_metadata(document)
        document_id = cls._parse_optional_int(metadata.get('document_id') or metadata.get('file_id'))
        if document_id not in (None, 0):
            return f'document:{document_id}'

        fallback_metadata = {
            'document_name': cls._extract_rag_document_name(metadata),
            'knowledge_id': cls._parse_optional_int(metadata.get('knowledge_id')),
            'file_type': cls._extract_rag_file_type(metadata),
            'source_url': cls._parse_optional_text(
                (metadata.get('user_metadata') or {}).get('url') or metadata.get('source_url')
            ),
            'upload_time': cls._parse_optional_int(metadata.get('upload_time')),
        }
        normalized_metadata = {key: value for key, value in fallback_metadata.items() if value not in (None, '')}
        if normalized_metadata:
            return f"metadata:{json.dumps(normalized_metadata, sort_keys=True, ensure_ascii=False)}"

        return f'fallback:{index}'

    @classmethod
    def _build_rag_payload(cls, documents: List[Document]) -> RagCitationPayloadSchema:
        """Build a grouped RAG payload for all chunks in one file."""
        return cls._build_rag_payload_with_knowledge_names(documents=documents, knowledge_names={})

    @classmethod
    def _load_knowledge_names(cls, documents: List[Document]) -> Dict[int, str]:
        """Load knowledge display names in batch for retrieved documents."""
        knowledge_ids = {
            knowledge_id
            for document in documents
            for knowledge_id in [cls._parse_optional_int(cls._parse_metadata(document).get('knowledge_id'))]
            if knowledge_id is not None
        }
        if not knowledge_ids:
            return {}

        knowledges = KnowledgeDao.get_list_by_ids(sorted(knowledge_ids))
        return {
            knowledge.id: knowledge.name
            for knowledge in knowledges
            if getattr(knowledge, 'id', None) is not None and getattr(knowledge, 'name', None)
        }

    @classmethod
    def _build_rag_payload_with_knowledge_names(
            cls,
            documents: List[Document],
            knowledge_names: Dict[int, str],
    ) -> RagCitationPayloadSchema:
        """Build a grouped RAG payload for all chunks in one file."""
        if not documents:
            return RagCitationPayloadSchema(items=[])

        first_metadata = cls._parse_metadata(documents[0])
        knowledge_id = cls._parse_optional_int(first_metadata.get('knowledge_id'))
        document_id = cls._parse_optional_int(first_metadata.get('document_id') or first_metadata.get('file_id'))
        document_name = cls._extract_rag_document_name(first_metadata)
        file_type = cls._extract_rag_file_type(first_metadata)
        knowledge_name = cls._parse_optional_text(
            first_metadata.get('knowledge_name')
            or first_metadata.get('knowledgeName')
            or first_metadata.get('knowledge')
        )
        if not knowledge_name and knowledge_id is not None:
            knowledge_name = cls._parse_optional_text(knowledge_names.get(knowledge_id))
        items = [cls._build_rag_chunk_item(document=document) for document in documents]
        first_item = items[0] if items else None

        return RagCitationPayloadSchema(
            knowledgeId=knowledge_id,
            knowledgeName=knowledge_name,
            fileType=file_type,
            documentId=document_id,
            documentName=document_name,
            snippet=first_item.content if first_item else None,
            previewUrl=cls._parse_optional_text(first_metadata.get('preview_url') or first_metadata.get('previewUrl')),
            downloadUrl=cls._parse_optional_text(
                first_metadata.get('download_url') or first_metadata.get('downloadUrl')),
            sourceUrl=cls._parse_optional_text(
                (first_metadata.get('user_metadata') or {}).get('url') or first_metadata.get('source_url')
            ),
            items=items,
        )

    @classmethod
    def _flatten_rag_payload(
            cls,
            citation_id: str,
            payload: RagCitationPayloadSchema,
    ) -> List[CitationRegistryItemSchema]:
        """Flatten a grouped RAG payload into item-level registry entries."""
        registry_items: List[CitationRegistryItemSchema] = []
        for item in payload.items:
            item_payload = payload.model_copy(
                update={
                    'snippet': item.content,
                    'items': [item],
                }
            )
            registry_items.append(
                CitationRegistryItemSchema(
                    key=cls.build_item_key(citation_id, item.itemId),
                    citationId=citation_id,
                    type=CitationType.RAG,
                    itemId=item.itemId,
                    sourcePayload=item_payload,
                )
            )
        return registry_items

    @classmethod
    def _group_rag_flat_items(
            cls,
            items: List[CitationRegistryItemSchema],
    ) -> CitationRegistryItemSchema:
        """Rebuild one grouped RAG registry item from flattened records."""
        first_item = items[0]
        payloads = [RagCitationPayloadSchema.model_validate(item.sourcePayload) for item in items]
        chunk_items: List[RagCitationItemSchema] = []
        for payload in payloads:
            chunk_items.extend(payload.items)
        grouped_payload = payloads[0].model_copy(
            update={
                'snippet': chunk_items[0].content if chunk_items else payloads[0].snippet,
                'items': chunk_items,
            }
        )
        return CitationRegistryItemSchema(
            citationId=first_item.citationId,
            type=CitationType.RAG,
            sourcePayload=grouped_payload,
        )

    @classmethod
    def build_rag_registry(
            cls,
            documents: List[Document],
    ) -> List[CitationRegistryItemSchema]:
        """Build flattened registry items from retrieved RAG documents."""
        if not documents:
            return []

        knowledge_names = cls._load_knowledge_names(documents)
        grouped_documents: "OrderedDict[str, List[Document]]" = OrderedDict()
        for index, document in enumerate(documents):
            grouping_id = cls._build_rag_grouping_key(document, index)
            grouped_documents.setdefault(grouping_id, []).append(document)

        registry_items: List[CitationRegistryItemSchema] = []
        for grouped_docs in grouped_documents.values():
            citation_id = cls.generate_rag_citation_id()
            payload = cls._build_rag_payload_with_knowledge_names(grouped_docs, knowledge_names)
            registry_items.extend(cls._flatten_rag_payload(citation_id, payload))
        return registry_items

    @classmethod
    def _build_web_item(
            cls,
            result: Dict[str, Any],
            index: int = 0,
    ) -> WebCitationItemSchema:
        """Build a snippet-level payload item from a web search result."""
        return WebCitationItemSchema(
            itemId=cls.build_web_item_id(result=result, index=index),
            snippet=cls._parse_optional_text(result.get('snippet') or result.get('summary')),
            title=cls._parse_optional_text(result.get('title') or result.get('name')),
        )

    @classmethod
    def build_web_item_id(
            cls,
            result: Dict[str, Any],
            index: int = 0,
    ) -> str:
        """Build the model-facing web citation item identifier."""
        for key in ('itemId', 'snippetId'):
            item_id = cls._parse_optional_text(result.get(key))
            if item_id:
                return item_id
        return str(index + 1)

    @classmethod
    def _build_web_payload(
            cls,
            normalized_url: str,
            results: List[Dict[str, Any]],
    ) -> WebCitationPayloadSchema:
        """Build a grouped web payload for all snippets in one page."""
        first_result = results[0]
        web_items = [cls._build_web_item(result=result, index=index) for index, result in enumerate(results)]
        first_item = web_items[0] if web_items else None
        return WebCitationPayloadSchema(
            url=normalized_url,
            title=cls._parse_optional_text(first_result.get('title') or first_result.get('name')),
            snippet=first_item.snippet if first_item else None,
            source=cls._parse_optional_text(
                first_result.get('source') or first_result.get('siteName') or first_result.get('site_name')
            ),
            siteIcon=cls._parse_optional_text(
                first_result.get('siteIcon') or first_result.get('faviconUrl') or first_result.get('favicon_url')
            ),
            datePublished=cls._parse_optional_text(
                first_result.get('datePublished') or first_result.get('publishedAt') or first_result.get('published_at')
            ),
            items=web_items,
        )

    @classmethod
    def _flatten_web_payload(
            cls,
            citation_id: str,
            payload: WebCitationPayloadSchema,
    ) -> List[CitationRegistryItemSchema]:
        """Flatten a grouped web payload into item-level registry entries."""
        registry_items: List[CitationRegistryItemSchema] = []
        for item in payload.items:
            item_payload = payload.model_copy(
                update={
                    'snippet': item.snippet,
                    'items': [item],
                }
            )
            registry_items.append(
                CitationRegistryItemSchema(
                    key=cls.build_item_key(citation_id, item.itemId),
                    citationId=citation_id,
                    type=CitationType.WEB,
                    itemId=item.itemId,
                    sourcePayload=item_payload,
                )
            )
        return registry_items

    @classmethod
    def _group_web_flat_items(
            cls,
            items: List[CitationRegistryItemSchema],
    ) -> CitationRegistryItemSchema:
        """Rebuild one grouped web registry item from flattened records."""
        first_item = items[0]
        payloads = [WebCitationPayloadSchema.model_validate(item.sourcePayload) for item in items]
        web_items: List[WebCitationItemSchema] = []
        for payload in payloads:
            web_items.extend(payload.items)
        grouped_payload = payloads[0].model_copy(
            update={
                'snippet': web_items[0].snippet if web_items else payloads[0].snippet,
                'items': web_items,
            }
        )
        return CitationRegistryItemSchema(
            citationId=first_item.citationId,
            type=CitationType.WEB,
            sourcePayload=grouped_payload,
        )

    @classmethod
    def build_web_registry(
            cls,
            results: List[Dict[str, Any]],
    ) -> List[CitationRegistryItemSchema]:
        """Build flattened registry items from web search results."""
        if not results:
            return []

        grouped_results: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
        for result in results:
            raw_url = cls._parse_optional_text(result.get('url') or result.get('link')) or ''
            normalized_url = cls.normalize_url(raw_url)
            grouped_results.setdefault(normalized_url, []).append(result)

        registry_items: List[CitationRegistryItemSchema] = []
        for normalized_url, grouped_page_results in grouped_results.items():
            citation_id = cls.generate_web_citation_id()
            payload = cls._build_web_payload(normalized_url, grouped_page_results)
            registry_items.extend(cls._flatten_web_payload(citation_id, payload))
        return registry_items

    @classmethod
    def _group_registry_items(
            cls,
            items: List[CitationRegistryItemSchema],
    ) -> List[CitationRegistryItemSchema]:
        """Group item-level registry entries into persisted citation records."""
        grouped_items: "OrderedDict[str, List[CitationRegistryItemSchema]]" = OrderedDict()
        for item in items:
            grouped_items.setdefault(item.citationId, []).append(item)

        registry_items: List[CitationRegistryItemSchema] = []
        for grouped_flat_items in grouped_items.values():
            first_item = grouped_flat_items[0]
            if first_item.type == CitationType.RAG:
                registry_items.append(cls._group_rag_flat_items(grouped_flat_items))
            else:
                registry_items.append(cls._group_web_flat_items(grouped_flat_items))
        return registry_items

    async def save_citations(
            self,
            message_id: int,
            items: List[CitationRegistryItemSchema],
            chat_id: Optional[str] = None,
            flow_id: Optional[str] = None,
    ) -> List[MessageCitation]:
        """Persist normalized citation items for a message."""
        if not items:
            return []

        existing_entities = await self.repository.find_by_message_id(message_id)
        existing_by_citation_id = {entity.citation_id: entity for entity in existing_entities}

        grouped_items = self._group_registry_items(items)
        unique_items: "OrderedDict[str, CitationRegistryItemSchema]" = OrderedDict()
        for item in grouped_items:
            unique_items[item.citationId] = item

        entities = [
            MessageCitation(
                citation_id=item.citationId,
                message_id=message_id,
                chat_id=chat_id,
                flow_id=flow_id,
                citation_type=item.type.value,
                source_payload=self._dump_source_payload(item.sourcePayload),
            )
            for item in unique_items.values()
            if item.citationId not in existing_by_citation_id
        ]

        if entities:
            created_entities = await self.repository.bulk_create(entities)
            existing_entities.extend(created_entities)

        return sorted(existing_entities, key=lambda item: item.id or 0)

    def save_citations_sync(
            self,
            message_id: int,
            items: List[CitationRegistryItemSchema],
            chat_id: Optional[str] = None,
            flow_id: Optional[str] = None,
    ) -> List[MessageCitation]:
        """Persist normalized citation items for a message synchronously."""
        if not items:
            return []

        find_by_message_id_sync = getattr(self.repository, 'find_by_message_id_sync')
        bulk_create_sync = getattr(self.repository, 'bulk_create_sync')

        existing_entities = find_by_message_id_sync(message_id)
        existing_by_citation_id = {entity.citation_id: entity for entity in existing_entities}

        grouped_items = self._group_registry_items(items)
        unique_items: "OrderedDict[str, CitationRegistryItemSchema]" = OrderedDict()
        for item in grouped_items:
            unique_items[item.citationId] = item

        entities = [
            MessageCitation(
                citation_id=item.citationId,
                message_id=message_id,
                chat_id=chat_id,
                flow_id=flow_id,
                citation_type=item.type.value,
                source_payload=self.dump_source_payload(item.sourcePayload),
            )
            for item in unique_items.values()
            if item.citationId not in existing_by_citation_id
        ]

        if entities:
            created_entities = bulk_create_sync(entities)
            existing_entities.extend(created_entities)

        return sorted(existing_entities, key=lambda item: item.id or 0)

    def to_registry_item(self, citation: MessageCitation) -> CitationRegistryItemSchema:
        """Convert a persisted citation entity to schema."""
        source_payload = self._load_source_payload(citation.citation_type, citation.source_payload)
        return CitationRegistryItemSchema(
            citationId=citation.citation_id,
            type=CitationType(citation.citation_type),
            sourcePayload=source_payload,
        )

    async def list_message_citations(self, message_id: int) -> List[CitationRegistryItemSchema]:
        """List all normalized citation items for a message."""
        citations = await self.repository.find_by_message_id(message_id)
        return [self.to_registry_item(citation) for citation in citations]

    async def get_citation(self, citation_id: str) -> Optional[CitationRegistryItemSchema]:
        """Get one normalized citation item by business ID."""
        citation = await self.repository.find_by_citation_id(citation_id)
        if citation is None:
            return None
        return self.to_registry_item(citation)

    async def list_citations_by_ids(self, citation_ids: List[str]) -> List[CitationRegistryItemSchema]:
        """List normalized citation items by business IDs."""
        citations = await self.repository.find_by_citation_ids(citation_ids)
        citation_map = {citation.citation_id: self.to_registry_item(citation) for citation in citations}
        return [citation_map[citation_id] for citation_id in citation_ids if citation_id in citation_map]
