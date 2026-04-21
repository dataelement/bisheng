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


class RagCitationItemSchema(CitationSchemaBase):
    """Chunk-level payload inside a grouped RAG citation item."""

    itemId: str = Field(..., description='Stable item identifier inside the citation')
    chunkId: Optional[str] = Field(default=None, description='Chunk identifier')
    chunkIndex: Optional[int] = Field(default=None, description='Chunk index inside the file')
    content: Optional[str] = Field(default=None, description='Chunk content')
    bbox: Optional[str] = Field(default=None, description='Bounding box information')
    page: Optional[int] = Field(default=None, description='Page number')


class RagCitationPayloadSchema(CitationSchemaBase):
    """Payload for knowledge-based citation items."""

    knowledgeId: Optional[int] = Field(default=None, description='Knowledge space identifier')
    knowledgeName: Optional[str] = Field(default=None, description='Knowledge space display name')
    fileType: Optional[str] = Field(default=None, description='Knowledge file type')
    documentId: Optional[int] = Field(default=None, description='Document identifier')
    documentName: Optional[str] = Field(default=None, description='Document display name')
    snippet: Optional[str] = Field(default=None, description='Matched chunk text snippet')
    previewUrl: Optional[str] = Field(default=None, description='Document preview URL')
    downloadUrl: Optional[str] = Field(default=None, description='Document download URL')
    sourceUrl: Optional[str] = Field(default=None, description='Original source URL if available')
    items: List[RagCitationItemSchema] = Field(
        default_factory=list,
        description='Grouped chunk items for the same file',
    )


class WebCitationItemSchema(CitationSchemaBase):
    """Snippet-level payload inside a grouped web citation item."""

    itemId: str = Field(..., description='Stable item identifier inside the citation')
    snippet: Optional[str] = Field(default=None, description='Matched snippet content')
    title: Optional[str] = Field(default=None, description='Snippet title override if needed')


class WebCitationPayloadSchema(CitationSchemaBase):
    """Payload for web search citation items."""

    url: str = Field(..., description='Canonical web page URL')
    title: Optional[str] = Field(default=None, description='Web page title')
    snippet: Optional[str] = Field(default=None, description='Search result snippet')
    source: Optional[str] = Field(default=None, description='Search result source name')
    siteIcon: Optional[str] = Field(default=None, description='Site icon URL')
    datePublished: Optional[str] = Field(default=None, description='Published time in ISO 8601 string')
    items: List[WebCitationItemSchema] = Field(
        default_factory=list,
        description='Grouped snippet items for the same page',
    )


CitationSourcePayload = Union[RagCitationPayloadSchema, WebCitationPayloadSchema]


class CitationRegistryItemSchema(CitationSchemaBase):
    """Normalized citation registry item shared by all chains."""

    key: Optional[str] = Field(default=None, description='Flattened citation item key when item-level view is needed')
    citationId: str = Field(..., description='Unique citation identifier')
    type: CitationType = Field(..., description='Citation source type')
    itemId: Optional[str] = Field(default=None, description='Item identifier inside the parent citation')
    sourcePayload: CitationSourcePayload = Field(..., description='Structured source payload')


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
