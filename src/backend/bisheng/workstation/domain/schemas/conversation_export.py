"""DTO schemas for F028: workstation conversation export & import.

Two business flows share these DTOs:
- export: serialize selected ChatMessages into docx/pdf/md/txt for download
- import-to-knowledge: serialize the same selection into .md then add to a
  knowledge space via the existing upload pipeline
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


_MAX_BATCH = 200


class ExportFormat(str, Enum):
    """Supported export file formats (AC-02)."""

    DOCX = 'docx'
    PDF = 'pdf'
    MARKDOWN = 'md'
    TXT = 'txt'


class ExportMessagesRequest(BaseModel):
    """Request body for POST /api/v1/chat/messages/export."""

    chat_id: str = Field(..., description='Target chat id; all message_ids must belong to it')
    message_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=_MAX_BATCH,
        description=f'Message ids to export; at most {_MAX_BATCH} per request (AC-08)',
    )
    format: ExportFormat


class ImportMessagesToKnowledgeRequest(BaseModel):
    """Request body for POST /api/v1/chat/messages/import-to-knowledge."""

    chat_id: str
    message_ids: list[int] = Field(..., min_length=1, max_length=_MAX_BATCH)
    knowledge_space_id: int = Field(..., description='Target knowledge space id')
    parent_id: Optional[int] = Field(
        default=None,
        description='Target folder id; None means knowledge space root',
    )


class ImportMessagesToKnowledgeResponse(BaseModel):
    """Response body for the import endpoint."""

    file_id: int
    target_filename: str = Field(..., description='Final filename after dedup rename')
    dup_renamed: bool = Field(..., description='True when a (N) suffix was appended (AC-19)')


class UploadableSpaceItem(BaseModel):
    """One row in the uploadable-knowledge-space list."""

    id: int
    name: str
    icon: Optional[str] = None
    description: Optional[str] = None


class UploadableSpaceListResponse(BaseModel):
    """Response body for GET /api/v1/knowledge/space/uploadable.

    Not cursor-paginated: a single user's uploadable spaces are bounded (~<=100),
    INV-6 high-frequency-list rule does not apply. See spec §3 boundary notes.
    """

    data: list[UploadableSpaceItem]
