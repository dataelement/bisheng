"""全文索引收录判定与严格白名单文档组装。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextDocument,
    KnowledgeFulltextEngagementCounts,
    KnowledgeFulltextFileSnapshot,
)


class KnowledgeFulltextProjectionAction(str, Enum):
    UPSERT = "upsert"
    DELETE = "delete"
    KEEP = "keep"
    RETRY = "retry"


class KnowledgeFulltextDocumentService:
    TRANSIENT_STATUSES = frozenset({"WAITING", "PROCESSING", "REBUILDING", "5", "1"})
    SUCCESS_STATUSES = frozenset({"SUCCESS", "2"})
    DISTRIBUTED_ENTRY_TYPES = frozenset({"manager", "publish", "share"})

    def __init__(self, *, index_schema_version: int):
        self.index_schema_version = index_schema_version

    @classmethod
    def decide(cls, snapshot: KnowledgeFulltextFileSnapshot) -> KnowledgeFulltextProjectionAction:
        status = str(snapshot.status).upper()
        if snapshot.file_type.upper() != "FILE" or snapshot.deleted_at is not None:
            return KnowledgeFulltextProjectionAction.DELETE
        if status in cls.TRANSIENT_STATUSES:
            return KnowledgeFulltextProjectionAction.KEEP
        if status not in cls.SUCCESS_STATUSES:
            return KnowledgeFulltextProjectionAction.DELETE
        if snapshot.document_version_id is not None and not snapshot.is_primary_version:
            return KnowledgeFulltextProjectionAction.DELETE
        if snapshot.logical_document_id is None:
            return KnowledgeFulltextProjectionAction.UPSERT
        if snapshot.entry_type not in cls.DISTRIBUTED_ENTRY_TYPES:
            return KnowledgeFulltextProjectionAction.DELETE
        if snapshot.entry_status != "active" or not snapshot.is_primary_version:
            return KnowledgeFulltextProjectionAction.DELETE
        if snapshot.projection_status != "ready":
            return KnowledgeFulltextProjectionAction.KEEP
        return KnowledgeFulltextProjectionAction.UPSERT

    def build(
        self,
        snapshot: KnowledgeFulltextFileSnapshot,
        *,
        content: str,
        chunk_count: int,
        content_hash: str,
        sync_revision: int,
        indexed_at: datetime,
        engagement: KnowledgeFulltextEngagementCounts | None = None,
    ) -> KnowledgeFulltextDocument:
        title = (snapshot.alias_name or "").strip() or snapshot.file_name
        file_ext = snapshot.file_name.rsplit(".", 1)[-1].lower() if "." in snapshot.file_name else ""
        folder_path = (snapshot.folder_path or "").strip("/")
        source_path = snapshot.source_path or "/".join(
            part for part in (snapshot.knowledge_name, folder_path, snapshot.file_name) if part
        )
        return KnowledgeFulltextDocument(
            file_id=snapshot.file_id,
            knowledge_id=snapshot.knowledge_id,
            logical_document_id=snapshot.logical_document_id,
            document_version_id=snapshot.document_version_id,
            content_file_id=snapshot.content_file_id or snapshot.file_id,
            file_name=snapshot.file_name,
            display_title=title,
            summary=snapshot.summary,
            content=content,
            tags=list(dict.fromkeys(snapshot.tags)),
            knowledge_name=snapshot.knowledge_name,
            knowledge_type=snapshot.knowledge_type,
            knowledge_level=snapshot.knowledge_level,
            knowledge_business_domain_codes=snapshot.knowledge_business_domain_codes,
            business_domain_code=snapshot.business_domain_code,
            business_domain_name=snapshot.business_domain_name,
            document_category_code=snapshot.document_category_code,
            document_category_name=snapshot.document_category_name,
            file_subcategory_code=snapshot.file_subcategory_code,
            file_subcategory_name=snapshot.file_subcategory_name,
            file_ext=file_ext,
            file_source=snapshot.file_source,
            folder_path=snapshot.folder_path,
            source_path=source_path,
            uploader_id=snapshot.uploader_id,
            uploader_name=snapshot.uploader_name,
            original_uploader_id=snapshot.original_uploader_id,
            original_uploader_name=snapshot.original_uploader_name,
            original_knowledge_id=snapshot.original_knowledge_id,
            original_knowledge_name=snapshot.original_knowledge_name,
            updater_id=snapshot.updater_id,
            updater_name=snapshot.updater_name,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
            entry_type=snapshot.entry_type,
            entry_status=snapshot.entry_status,
            projection_status=snapshot.projection_status,
            allow_download=snapshot.allow_download,
            chunk_count=chunk_count,
            content_hash=content_hash,
            index_schema_version=self.index_schema_version,
            sync_revision=sync_revision,
            indexed_at=indexed_at,
            preview_count=engagement.preview_count if engagement else 0,
            download_count=engagement.download_count if engagement else 0,
            engagement_updated_at=indexed_at if engagement else None,
        )
