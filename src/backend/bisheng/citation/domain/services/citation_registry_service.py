import uuid
from collections import OrderedDict
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
    WebCitationPayloadSchema,
)


class CitationRegistryService:
    """Build and persist normalized citation registry items."""

    RAG_PREFIX = 'knowledgesearch_'
    WEB_PREFIX = 'websearch_'
    ID_SUFFIX_LENGTH = 12

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
        """Normalize a URL for group keys and persistence."""
        if not url:
            return ''

        parts = urlsplit(url.strip())
        scheme = (parts.scheme or 'https').lower()
        netloc = parts.netloc.lower()
        path = parts.path or '/'
        if path != '/' and path.endswith('/'):
            path = path.rstrip('/')
        return urlunsplit((scheme, netloc, path, parts.query, ''))

    @classmethod
    def build_rag_group_key(cls, file_id: Optional[int], document_id: Optional[int]) -> str:
        """Build the group key for a RAG citation."""
        target_file_id = file_id or document_id or 0
        return f'file:{target_file_id}'

    @classmethod
    def build_web_group_key(cls, url: str) -> str:
        """Build the group key for a web citation."""
        normalized_url = cls.normalize_url(url)
        return f'web:{normalized_url}'

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
    def _build_rag_chunk_item(cls, document: Document) -> RagCitationItemSchema:
        """Build a grouped chunk payload item from a retrieved document."""
        metadata = cls._parse_metadata(document)
        return RagCitationItemSchema(
            chunkId=cls._parse_optional_text(metadata.get('id') or metadata.get('chunk_id')),
            chunkIndex=cls._parse_optional_int(metadata.get('chunk_index')),
            content=document.page_content or None,
            bbox=cls._parse_optional_text(metadata.get('bbox')),
            page=cls._parse_optional_int(metadata.get('page')),
        )

    @classmethod
    def _build_rag_payload(cls, documents: List[Document]) -> RagCitationPayloadSchema:
        """Build a grouped RAG payload for all chunks in one file."""
        if not documents:
            return RagCitationPayloadSchema(items=[])

        first_metadata = cls._parse_metadata(documents[0])
        file_id = cls._parse_optional_int(first_metadata.get('file_id') or first_metadata.get('document_id'))
        document_id = cls._parse_optional_int(first_metadata.get('document_id') or first_metadata.get('file_id'))
        file_name = cls._parse_optional_text(
            first_metadata.get('file_name')
            or first_metadata.get('document_name')
            or first_metadata.get('name')
            or first_metadata.get('source')
        )
        file_type = cls._parse_optional_text(
            first_metadata.get('file_type')
            or first_metadata.get('document_type')
            or first_metadata.get('suffix')
            or first_metadata.get('mime_type')
        )
        knowledge_name = cls._parse_optional_text(
            first_metadata.get('knowledge_name')
            or first_metadata.get('knowledgeName')
            or first_metadata.get('knowledge')
        )
        items = [cls._build_rag_chunk_item(document=document) for document in documents]
        first_item = items[0] if items else None

        return RagCitationPayloadSchema(
            knowledgeId=cls._parse_optional_int(first_metadata.get('knowledge_id')),
            knowledgeName=knowledge_name,
            fileId=file_id,
            fileName=file_name,
            fileType=file_type,
            documentId=document_id,
            documentName=file_name,
            chunkId=first_item.chunkId if first_item else None,
            chunkIndex=first_item.chunkIndex if first_item else None,
            page=first_item.page if first_item else None,
            bbox=first_item.bbox if first_item else None,
            content=first_item.content if first_item else None,
            snippet=first_item.content if first_item else None,
            previewUrl=cls._parse_optional_text(first_metadata.get('preview_url') or first_metadata.get('previewUrl')),
            downloadUrl=cls._parse_optional_text(first_metadata.get('download_url') or first_metadata.get('downloadUrl')),
            sourceUrl=cls._parse_optional_text(
                (first_metadata.get('user_metadata') or {}).get('url') or first_metadata.get('source_url')
            ),
            items=items,
        )

    @classmethod
    def build_rag_registry_item(
        cls,
        document: Document,
        display_order: int,
        citation_id: Optional[str] = None,
    ) -> CitationRegistryItemSchema:
        """Build a normalized registry item from a retrieved RAG document."""
        payload = cls._build_rag_payload([document])
        return CitationRegistryItemSchema(
            citationId=citation_id or cls.generate_rag_citation_id(),
            type=CitationType.RAG,
            groupKey=cls.build_rag_group_key(payload.fileId, payload.documentId),
            displayOrder=display_order,
            sourcePayload=payload,
        )

    @classmethod
    def build_rag_registry(
        cls,
        documents: List[Document],
        start_display_order: int = 1,
    ) -> List[CitationRegistryItemSchema]:
        """Build grouped normalized registry items from retrieved RAG documents."""
        if not documents:
            return []

        grouped_documents: "OrderedDict[str, List[Document]]" = OrderedDict()
        for document in documents:
            metadata = cls._parse_metadata(document)
            file_id = cls._parse_optional_int(metadata.get('file_id') or metadata.get('document_id'))
            document_id = cls._parse_optional_int(metadata.get('document_id') or metadata.get('file_id'))
            group_key = cls.build_rag_group_key(file_id, document_id)
            grouped_documents.setdefault(group_key, []).append(document)

        registry_items: List[CitationRegistryItemSchema] = []
        for index, grouped_docs in enumerate(grouped_documents.values()):
            payload = cls._build_rag_payload(grouped_docs)
            registry_items.append(
                CitationRegistryItemSchema(
                    citationId=cls.generate_rag_citation_id(),
                    type=CitationType.RAG,
                    groupKey=cls.build_rag_group_key(payload.fileId, payload.documentId),
                    displayOrder=start_display_order + index,
                    sourcePayload=payload,
                )
            )
        return registry_items

    @classmethod
    def build_web_registry_item(
        cls,
        result: Dict[str, Any],
        display_order: int,
        citation_id: Optional[str] = None,
    ) -> CitationRegistryItemSchema:
        """Build a normalized registry item from a web search result."""
        raw_url = cls._parse_optional_text(result.get('url') or result.get('link')) or ''
        normalized_url = cls.normalize_url(raw_url)
        payload = WebCitationPayloadSchema(
            url=normalized_url,
            title=cls._parse_optional_text(result.get('title') or result.get('name')),
            snippet=cls._parse_optional_text(result.get('snippet') or result.get('summary')),
            source=cls._parse_optional_text(result.get('source') or result.get('siteName') or result.get('site_name')),
            siteIcon=cls._parse_optional_text(
                result.get('siteIcon') or result.get('faviconUrl') or result.get('favicon_url')
            ),
            datePublished=cls._parse_optional_text(
                result.get('datePublished') or result.get('publishedAt') or result.get('published_at')
            ),
        )
        return CitationRegistryItemSchema(
            citationId=citation_id or cls.generate_web_citation_id(),
            type=CitationType.WEB,
            groupKey=cls.build_web_group_key(payload.url),
            displayOrder=display_order,
            sourcePayload=payload,
        )

    @classmethod
    def build_web_registry(
        cls,
        results: List[Dict[str, Any]],
        start_display_order: int = 1,
    ) -> List[CitationRegistryItemSchema]:
        """Build normalized registry items from web search results."""
        return [
            cls.build_web_registry_item(result=result, display_order=start_display_order + index)
            for index, result in enumerate(results)
        ]

    @staticmethod
    def build_rag_prompt_context(items: List[CitationRegistryItemSchema]) -> str:
        """Build a prompt context string with explicit citation markers."""
        if not items:
            return ''

        sections: List[str] = [
            'Use citation markers in the format [[ref:<citation_id>]] when referencing the evidence below.',
        ]
        for item in items:
            payload = RagCitationPayloadSchema.model_validate(item.sourcePayload)
            title = payload.fileName or payload.documentName or f'File {payload.fileId or payload.documentId or ""}'.strip()
            header = f'[[ref:{item.citationId}]] {title}'.strip()
            meta_bits: List[str] = []
            if payload.knowledgeName:
                meta_bits.append(f'knowledge={payload.knowledgeName}')
            if payload.fileType:
                meta_bits.append(f'type={payload.fileType}')
            if payload.previewUrl:
                meta_bits.append(f'preview={payload.previewUrl}')
            if payload.downloadUrl:
                meta_bits.append(f'download={payload.downloadUrl}')
            if meta_bits:
                header = f"{header} ({'; '.join(meta_bits)})"

            chunk_lines: List[str] = [header]
            for chunk_index, chunk in enumerate(payload.items, start=1):
                chunk_title_bits: List[str] = [f'chunk={chunk_index}']
                if chunk.chunkId:
                    chunk_title_bits.append(f'id={chunk.chunkId}')
                if chunk.chunkIndex is not None:
                    chunk_title_bits.append(f'index={chunk.chunkIndex}')
                if chunk.page is not None:
                    chunk_title_bits.append(f'page={chunk.page}')
                if chunk.bbox:
                    chunk_title_bits.append(f'bbox={chunk.bbox}')
                chunk_title = ' | '.join(chunk_title_bits)
                chunk_content = (chunk.content or '').strip()
                if chunk_content:
                    chunk_lines.append(f'- {chunk_title}\n{chunk_content}')
                else:
                    chunk_lines.append(f'- {chunk_title}')
            sections.append('\n'.join(chunk_lines))

        return '\n\n'.join(sections)

    @staticmethod
    def build_web_prompt_context(items: List[CitationRegistryItemSchema]) -> str:
        """Build a prompt context string with explicit citation markers for web results."""
        if not items:
            return ''

        sections: List[str] = [
            'Use citation markers in the format [[ref:<citation_id>]] when referencing the web results below.',
        ]
        for item in items:
            payload = WebCitationPayloadSchema.model_validate(item.sourcePayload)
            lines: List[str] = [f'[[ref:{item.citationId}]] {payload.title or payload.url}']
            meta_bits: List[str] = []
            if payload.source:
                meta_bits.append(f'source={payload.source}')
            if payload.datePublished:
                meta_bits.append(f'datePublished={payload.datePublished}')
            if payload.url:
                meta_bits.append(f'url={payload.url}')
            if meta_bits:
                lines.append(f"meta: {'; '.join(meta_bits)}")
            if payload.snippet:
                lines.append(payload.snippet)
            sections.append('\n'.join(lines))

        return '\n\n'.join(sections)

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

        unique_items: "OrderedDict[str, CitationRegistryItemSchema]" = OrderedDict()
        for item in items:
            unique_items[item.citationId] = item

        entities = [
            MessageCitation(
                citation_id=item.citationId,
                message_id=message_id,
                chat_id=chat_id,
                flow_id=flow_id,
                citation_type=item.type.value,
                group_key=item.groupKey,
                display_order=item.displayOrder,
                source_payload=self._dump_source_payload(item.sourcePayload),
            )
            for item in unique_items.values()
            if item.citationId not in existing_by_citation_id
        ]

        if entities:
            created_entities = await self.repository.bulk_create(entities)
            existing_entities.extend(created_entities)

        return sorted(existing_entities, key=lambda item: (item.display_order, item.id or 0))

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

        unique_items: "OrderedDict[str, CitationRegistryItemSchema]" = OrderedDict()
        for item in items:
            unique_items[item.citationId] = item

        entities = [
            MessageCitation(
                citation_id=item.citationId,
                message_id=message_id,
                chat_id=chat_id,
                flow_id=flow_id,
                citation_type=item.type.value,
                group_key=item.groupKey,
                display_order=item.displayOrder,
                source_payload=self.dump_source_payload(item.sourcePayload),
            )
            for item in unique_items.values()
            if item.citationId not in existing_by_citation_id
        ]

        if entities:
            created_entities = bulk_create_sync(entities)
            existing_entities.extend(created_entities)

        return sorted(existing_entities, key=lambda item: (item.display_order, item.id or 0))

    def to_registry_item(self, citation: MessageCitation) -> CitationRegistryItemSchema:
        """Convert a persisted citation entity to schema."""
        source_payload = self._load_source_payload(citation.citation_type, citation.source_payload)
        return CitationRegistryItemSchema(
            citationId=citation.citation_id,
            type=CitationType(citation.citation_type),
            groupKey=citation.group_key or '',
            displayOrder=citation.display_order,
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
