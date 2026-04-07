from enum import Enum
from typing import Any, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class CitationSchemaBase(BaseModel):
    """Base schema for citation protocol models."""

    model_config = ConfigDict(
        validate_by_alias=True,
        validate_by_name=True,
        arbitrary_types_allowed=True,
    )


class CitationType(str, Enum):
    """Supported citation source types."""

    RAG = 'rag'
    WEB = 'web'


class CitationFragmentSchema(CitationSchemaBase):
    """Reference fragment embedded in answer content."""

    citationId: str = Field(..., description='Unique citation identifier')
    type: Optional[CitationType] = Field(default=None, description='Citation source type')
    groupKey: Optional[str] = Field(default=None, description='Display grouping key')


class RagCitationItemSchema(CitationSchemaBase):
    """Chunk-level payload inside a grouped RAG citation item."""

    chunkId: Optional[str] = Field(default=None, description='Chunk identifier')
    chunkIndex: Optional[int] = Field(default=None, description='Chunk index inside the file')
    content: Optional[str] = Field(default=None, description='Chunk content')
    bbox: Optional[str] = Field(default=None, description='Bounding box information')
    page: Optional[int] = Field(default=None, description='Page number')


class RagCitationPayloadSchema(CitationSchemaBase):
    """Payload for knowledge-based citation items."""

    knowledgeId: Optional[int] = Field(default=None, description='Knowledge space identifier')
    knowledgeName: Optional[str] = Field(default=None, description='Knowledge space display name')
    fileId: Optional[int] = Field(default=None, description='Knowledge file identifier')
    fileName: Optional[str] = Field(default=None, description='Knowledge file display name')
    fileType: Optional[str] = Field(default=None, description='Knowledge file type')
    documentId: Optional[int] = Field(default=None, description='Document identifier')
    documentName: Optional[str] = Field(default=None, description='Document display name')
    chunkId: Optional[str] = Field(default=None, description='Chunk identifier')
    chunkIndex: Optional[int] = Field(default=None, description='Chunk index inside document')
    page: Optional[int] = Field(default=None, description='Page number')
    bbox: Optional[str] = Field(default=None, description='Bounding box information')
    content: Optional[str] = Field(default=None, description='Primary chunk content')
    snippet: Optional[str] = Field(default=None, description='Matched chunk text snippet')
    previewUrl: Optional[str] = Field(default=None, description='Document preview URL')
    downloadUrl: Optional[str] = Field(default=None, description='Document download URL')
    sourceUrl: Optional[str] = Field(default=None, description='Original source URL if available')
    items: List[RagCitationItemSchema] = Field(
        default_factory=list,
        description='Grouped chunk items for the same file',
    )


class WebCitationPayloadSchema(CitationSchemaBase):
    """Payload for web search citation items."""

    url: str = Field(..., description='Canonical web page URL')
    title: Optional[str] = Field(default=None, description='Web page title')
    snippet: Optional[str] = Field(default=None, description='Search result snippet')
    source: Optional[str] = Field(default=None, description='Search result source name')
    siteIcon: Optional[str] = Field(default=None, description='Site icon URL')
    datePublished: Optional[str] = Field(default=None, description='Published time in ISO 8601 string')


CitationSourcePayload = Union[RagCitationPayloadSchema, WebCitationPayloadSchema]


class CitationRegistryItemSchema(CitationSchemaBase):
    """Normalized citation registry item shared by all chains."""

    citationId: str = Field(..., description='Unique citation identifier')
    type: CitationType = Field(..., description='Citation source type')
    groupKey: str = Field(..., description='Display grouping key')
    sourcePayload: CitationSourcePayload = Field(..., description='Structured source payload')


class RagRetrievalResultSchema(CitationSchemaBase):
    """Structured result returned by RAG retrieval tools."""

    prompt_context: str = Field(default='', description='Formatted prompt context with citation markers')
    source_documents: List[Any] = Field(default_factory=list, description='Original retrieved documents')
    citation_registry: List[CitationRegistryItemSchema] = Field(
        default_factory=list,
        description='Normalized citation registry items',
    )

    def __iter__(self):
        """Iterate over source documents for backward compatibility."""
        return iter(self.source_documents)

    def __len__(self) -> int:
        """Return the number of source documents for backward compatibility."""
        return len(self.source_documents)

    def __bool__(self) -> bool:
        """Preserve list-like truthiness semantics."""
        return bool(self.source_documents)

    def __getitem__(self, index):
        """Allow index access for legacy list-style consumers."""
        return self.source_documents[index]


class ResolveCitationRequest(CitationSchemaBase):
    """Batch resolve request for citation items."""

    citationIds: List[str] = Field(default_factory=list, description='Citation identifiers to resolve')


class ResolveCitationResponse(CitationSchemaBase):
    """Batch resolve response for citation items."""

    items: List[CitationRegistryItemSchema] = Field(default_factory=list, description='Resolved citation items')


class CitationRegistrySSEPayload(CitationSchemaBase):
    """SSE payload for registry emission."""

    messageId: Optional[str] = Field(default=None, description='Message identifier for citation registry')
    items: List[CitationRegistryItemSchema] = Field(default_factory=list, description='Citation registry items')
