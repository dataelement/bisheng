from enum import Enum
from typing import Literal, Union

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

    RAG = "rag"
    WEB = "web"
    # F054: a channel article read whole into the prompt. Deliberately its own
    # type rather than a WEB citation reusing sourceUrl: article visibility is
    # governed by the channel's own sensitive-content gate, the badge has to be
    # distinguishable from a web-search hit, and the article doc id is what an
    # in-app jump would need — folding it into WEB throws all three away.
    ARTICLE = "article"


class RagCitationItemSchema(CitationSchemaBase):
    """Chunk-level payload inside a grouped RAG citation item."""

    itemId: str = Field(..., description="Stable item identifier inside the citation")
    chunkId: str | None = Field(default=None, description="Chunk identifier")
    chunkIndex: int | None = Field(default=None, description="Chunk index inside the file")
    content: str | None = Field(default=None, description="Chunk content")
    bbox: str | None = Field(default=None, description="Bounding box information")
    page: int | None = Field(default=None, description="Page number")


class RagCitationPayloadSchema(CitationSchemaBase):
    """Payload for knowledge-based citation items."""

    knowledgeId: int | None = Field(default=None, description="Knowledge space identifier")
    knowledgeName: str | None = Field(default=None, description="Knowledge space display name")
    fileType: str | None = Field(default=None, description="Knowledge file type")
    documentId: int | None = Field(default=None, description="Document identifier")
    documentName: str | None = Field(default=None, description="Document display name")
    snippet: str | None = Field(default=None, description="Matched chunk text snippet")
    previewUrl: str | None = Field(default=None, description="Document preview URL")
    downloadUrl: str | None = Field(default=None, description="Document download URL")
    sourceUrl: str | None = Field(default=None, description="Original source URL if available")
    items: list[RagCitationItemSchema] = Field(
        default_factory=list,
        description="Grouped chunk items for the same file",
    )


class ArticleCitationItemSchema(CitationSchemaBase):
    """Snippet-level payload inside a grouped article citation item."""

    itemId: str = Field(..., description="Stable item identifier inside the citation")
    snippet: str | None = Field(default=None, description="Quoted article excerpt")
    title: str | None = Field(default=None, description="Section title override if needed")


class ArticleCitationPayloadSchema(CitationSchemaBase):
    """Payload for channel-article citation items.

    The article is handed to the model whole (channel QA does not retrieve),
    so one article is one citation with a single item — there is no chunk to
    address. ``articleDocId`` is the real, stable locator; no knowledge-chunk
    id is ever synthesised for it.
    """

    articleDocId: str = Field(..., description="Channel article document identifier")
    title: str | None = Field(default=None, description="Article title")
    snippet: str | None = Field(default=None, description="Quoted article excerpt")
    sourceUrl: str | None = Field(default=None, description="Original article URL")
    sourceType: int | None = Field(default=None, description="0-WeChat Official Account, 1-Website")
    items: list[ArticleCitationItemSchema] = Field(
        default_factory=list,
        description="Grouped excerpt items for the same article",
    )


class WebCitationItemSchema(CitationSchemaBase):
    """Snippet-level payload inside a grouped web citation item."""

    itemId: str = Field(..., description="Stable item identifier inside the citation")
    snippet: str | None = Field(default=None, description="Matched snippet content")
    title: str | None = Field(default=None, description="Snippet title override if needed")


class WebCitationPayloadSchema(CitationSchemaBase):
    """Payload for web search citation items."""

    url: str = Field(..., description="Canonical web page URL")
    title: str | None = Field(default=None, description="Web page title")
    snippet: str | None = Field(default=None, description="Search result snippet")
    source: str | None = Field(default=None, description="Search result source name")
    siteIcon: str | None = Field(default=None, description="Site icon URL")
    datePublished: str | None = Field(default=None, description="Published time in ISO 8601 string")
    items: list[WebCitationItemSchema] = Field(
        default_factory=list,
        description="Grouped snippet items for the same page",
    )


CitationSourcePayload = Union[RagCitationPayloadSchema, WebCitationPayloadSchema, ArticleCitationPayloadSchema]


class CitationRegistryItemSchema(CitationSchemaBase):
    """Normalized citation registry item shared by all chains."""

    key: str | None = Field(default=None, description="Flattened citation item key when item-level view is needed")
    citationId: str = Field(..., description="Unique citation identifier")
    type: CitationType = Field(..., description="Citation source type")
    itemId: str | None = Field(default=None, description="Item identifier inside the parent citation")
    sourcePayload: CitationSourcePayload = Field(..., description="Structured source payload")
    accessScope: Literal["per_user", "shared"] = Field(
        default="per_user",
        description=(
            "F041 retrieval access gate. 'per_user': resolve filters the citation by the viewing "
            "user's view_file (F029 strict, dropped when unauthorized). 'shared': config-author-scoped "
            "(toggle OFF) — resolve keeps source metadata but still gates full-file preview/download "
            "URLs by the viewer view_file."
        ),
    )


class ResolveCitationRequest(CitationSchemaBase):
    """Batch resolve request for citation items."""

    citationIds: list[str] = Field(default_factory=list, description="Citation identifiers to resolve")


class CitationUnresolvedReason(str, Enum):
    """Why a requested citation came back without a payload."""

    FORBIDDEN = "forbidden"
    EXPIRED = "expired"


class UnresolvedCitationSchema(CitationSchemaBase):
    """One requested citation the server declined or could not find."""

    citationId: str = Field(..., description="Citation identifier that was requested")
    reason: CitationUnresolvedReason = Field(..., description="Why it was not resolved")


class ResolveCitationResponse(CitationSchemaBase):
    """Batch resolve response for citation items."""

    items: list[CitationRegistryItemSchema] = Field(default_factory=list, description="Resolved citation items")
    # F054: previously an unresolvable citation was simply omitted, so the
    # reader could not tell "you may not see this" from "this source is gone"
    # and got one vague failure for both. Additive — older clients ignore it.
    unresolved: list[UnresolvedCitationSchema] = Field(
        default_factory=list,
        description="Requested citations that were declined or not found, with the reason",
    )


class CitationRegistrySSEPayload(CitationSchemaBase):
    """SSE payload for registry emission."""

    messageId: str | None = Field(default=None, description="Message identifier for citation registry")
    items: list[CitationRegistryItemSchema] = Field(default_factory=list, description="Citation registry items")
