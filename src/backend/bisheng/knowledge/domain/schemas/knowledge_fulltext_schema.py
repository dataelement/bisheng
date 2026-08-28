"""全文索引的严格输入、快照和 ES 文档契约。"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeFulltextChunk(StrictSchema):
    es_id: str
    document_id: int
    knowledge_id: int
    chunk_index: int = Field(ge=0)
    text: str


class KnowledgeFulltextChunkSource(StrictSchema):
    index_name: str
    file_id: int = Field(gt=0)
    knowledge_id: int = Field(gt=0)
    tenant_id: int | None = Field(default=None, gt=0)
    canonical_document_id: int | None = Field(default=None, gt=0)
    canonical_version_id: int | None = Field(default=None, gt=0)
    content_generation: int | None = Field(default=None, ge=0)
    routing: str | None = None

    @property
    def shared(self) -> bool:
        return all(
            value is not None
            for value in (
                self.tenant_id,
                self.canonical_document_id,
                self.canonical_version_id,
                self.content_generation,
            )
        )


class KnowledgeFulltextRebuiltContent(StrictSchema):
    content: str
    chunk_count: int = Field(ge=1)
    content_hash: str


class KnowledgeFulltextEngagementCounts(StrictSchema):
    file_id: int = Field(gt=0)
    preview_count: int = Field(default=0, ge=0)
    download_count: int = Field(default=0, ge=0)


class KnowledgeFulltextEngagementDaily(StrictSchema):
    file_id: int = Field(gt=0)
    local_date: str
    preview_count: int = Field(default=0, ge=0)
    download_count: int = Field(default=0, ge=0)


class KnowledgeFulltextEngagementHistoryPage(StrictSchema):
    records: list[KnowledgeFulltextEngagementDaily] = Field(default_factory=list)
    after_key: dict[str, object] | None = None


class KnowledgeFulltextEngagementBulkResult(StrictSchema):
    updated_ids: list[int] = Field(default_factory=list)
    noop_ids: list[int] = Field(default_factory=list)
    missing_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


class KnowledgeFulltextFileSnapshot(StrictSchema):
    file_id: int
    tenant_id: int = Field(default=1, gt=0)
    knowledge_id: int
    file_type: str
    status: str
    deleted_at: datetime | None = None
    logical_document_id: int | None = None
    document_version_id: int | None = None
    content_file_id: int | None = None
    content_generation: int = Field(default=0, ge=0)
    is_primary_version: bool = True
    file_name: str
    alias_name: str | None = None
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    knowledge_name: str
    knowledge_type: int | None = None
    knowledge_level: str | None = None
    knowledge_business_domain_codes: list[str] = Field(default_factory=list)
    business_domain_code: str | None = None
    business_domain_name: str | None = None
    document_category_code: str | None = None
    document_category_name: str | None = None
    file_subcategory_code: str | None = None
    file_subcategory_name: str | None = None
    file_source: str
    folder_path: str | None = None
    source_path: str | None = None
    uploader_id: int | None = None
    uploader_name: str | None = None
    original_uploader_id: int | None = None
    original_uploader_name: str | None = None
    original_knowledge_id: int | None = None
    original_knowledge_name: str | None = None
    updater_id: int | None = None
    updater_name: str | None = None
    created_at: datetime
    updated_at: datetime
    entry_type: str | None = None
    entry_status: str | None = None
    projection_status: str | None = None
    allow_download: bool = False
    user_metadata: dict = Field(default_factory=dict, exclude=True)


class KnowledgeFulltextAutoRepairSource(StrictSchema):
    file_id: int = Field(gt=0)
    knowledge_id: int = Field(gt=0)
    md5: str | None = None
    object_name: str | None = None
    split_rule: str | None = None
    desired_content_generation: int = Field(default=0, ge=0)


class KnowledgeFulltextDocument(StrictSchema):
    file_id: int
    knowledge_id: int
    logical_document_id: int | None = None
    document_version_id: int | None = None
    content_file_id: int
    file_name: str
    display_title: str
    summary: str | None = None
    content: str
    tags: list[str] = Field(default_factory=list)
    knowledge_name: str
    knowledge_type: int | None = None
    knowledge_level: str | None = None
    knowledge_business_domain_codes: list[str] = Field(default_factory=list)
    business_domain_code: str | None = None
    business_domain_name: str | None = None
    document_category_code: str | None = None
    document_category_name: str | None = None
    file_subcategory_code: str | None = None
    file_subcategory_name: str | None = None
    file_ext: str
    file_source: str
    folder_path: str | None = None
    source_path: str
    uploader_id: int | None = None
    uploader_name: str | None = None
    original_uploader_id: int | None = None
    original_uploader_name: str | None = None
    original_knowledge_id: int | None = None
    original_knowledge_name: str | None = None
    updater_id: int | None = None
    updater_name: str | None = None
    created_at: datetime
    updated_at: datetime
    entry_type: str | None = None
    entry_status: str | None = None
    projection_status: str | None = None
    allow_download: bool = False
    chunk_count: int = Field(ge=1)
    content_hash: str
    index_schema_version: int = Field(ge=1)
    sync_revision: int = Field(ge=1)
    indexed_at: datetime
    preview_count: int = Field(default=0, ge=0)
    download_count: int = Field(default=0, ge=0)
    engagement_updated_at: datetime | None = None

    @classmethod
    def minimal(
        cls,
        *,
        file_id: int,
        knowledge_id: int,
        file_name: str,
        content: str,
        sync_revision: int,
    ) -> KnowledgeFulltextDocument:
        now = datetime.now(timezone.utc)
        file_ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        return cls(
            file_id=file_id,
            knowledge_id=knowledge_id,
            content_file_id=file_id,
            file_name=file_name,
            display_title=file_name,
            content=content,
            knowledge_name="",
            file_ext=file_ext,
            file_source="unknown",
            source_path=file_name,
            created_at=now,
            updated_at=now,
            chunk_count=1,
            content_hash="",
            index_schema_version=1,
            sync_revision=sync_revision,
            indexed_at=now,
        )
