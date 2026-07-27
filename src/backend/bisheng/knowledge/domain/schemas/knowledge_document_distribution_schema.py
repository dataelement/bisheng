"""DTOs shared by F059 document distribution services and API adapters."""

from __future__ import annotations

from pydantic import BaseModel


class KnowledgeDocumentEntryCapabilities(BaseModel):
    can_view: bool = False
    can_preview: bool = False
    can_download: bool = False
    can_move: bool = False
    can_manage_members: bool = False
    can_edit_content: bool = False
    can_publish: bool = False
    can_share: bool = False
    can_delete: bool = False


class ResolvedKnowledgeDocumentEntry(BaseModel):
    tenant_id: int
    requested_space_id: int
    entry_file_id: int
    entry_type: str
    entry_status: str | None = None
    canonical_document_id: int | None = None
    canonical_version_id: int | None = None
    content_file_id: int
    manager_file_id: int
    manager_space_id: int
    content_generation: int = 0
    desired_content_generation: int = 0
    applied_content_generation: int = 0
    desired_entry_generation: int = 0
    applied_entry_generation: int = 0
    projection_status: str = "ready"
    projection_ready: bool = True
    capabilities: KnowledgeDocumentEntryCapabilities
