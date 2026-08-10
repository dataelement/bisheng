"""Contract tests for F059 document distribution persistence fields."""

from sqlalchemy import Boolean, Integer

from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocument,
    KnowledgeDocumentLifecycleStatus,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
)


def test_document_distribution_defaults_and_tenant_contract():
    document = KnowledgeDocument(knowledge_id=12, tenant_id=7)

    assert document.tenant_id == 7
    assert document.predecessor_logic_file_id is None
    assert document.content_generation == 0
    assert document.lifecycle_status == KnowledgeDocumentLifecycleStatus.ACTIVE.value

    tenant_column = KnowledgeDocument.__table__.c.tenant_id
    assert isinstance(tenant_column.type, Integer)
    assert tenant_column.nullable is False
    assert tenant_column.server_default is None


def test_document_distribution_indexes_are_explicit_and_stable():
    index_names = {index.name for index in KnowledgeDocument.__table__.indexes}

    assert index_names >= {
        "idx_kdoc_tenant_lifecycle",
        "idx_kdoc_tenant_content_generation",
        "idx_kdoc_tenant_predecessor",
    }


def test_file_distribution_defaults_do_not_change_file_source_semantics():
    entry = KnowledgeFile(
        knowledge_id=12,
        file_name="shared.pdf",
        tenant_id=7,
        reference_document_id=91,
        entry_type=KnowledgeFileEntryType.SHARE.value,
        entry_status=KnowledgeFileEntryStatus.PREPARING.value,
    )

    assert entry.entry_type == "share"
    assert entry.entry_status == "preparing"
    assert entry.allow_download is False
    assert entry.desired_content_generation == 0
    assert entry.applied_content_generation == 0
    assert entry.desired_entry_generation == 0
    assert entry.applied_entry_generation == 0
    assert entry.projection_status == KnowledgeFileProjectionStatus.PENDING.value
    assert entry.projection_retry_count == 0
    assert entry.file_source == "upload"

    allow_download_column = KnowledgeFile.__table__.c.allow_download
    assert isinstance(allow_download_column.type, Boolean)
    assert allow_download_column.nullable is False


def test_file_distribution_fields_and_indexes_match_projection_recovery_contract():
    fields = set(KnowledgeFile.model_fields)
    assert fields >= {
        "reference_document_id",
        "entry_type",
        "entry_status",
        "predecessor_logic_file_id",
        "share_source_file_id",
        "allow_download",
        "approval_instance_id",
        "projection_previous_file_id",
        "desired_content_generation",
        "applied_content_generation",
        "desired_entry_generation",
        "applied_entry_generation",
        "projection_status",
        "projection_retry_count",
        "projection_next_retry_at",
        "projection_lease_owner",
        "projection_lease_until",
        "projection_last_error",
    }

    index_names = {index.name for index in KnowledgeFile.__table__.indexes}
    assert index_names >= {
        "idx_kfile_document_space_status",
        "idx_kfile_document_type_status",
        "idx_kfile_projection_retry_lease",
        "idx_kfile_entry_cleanup",
        "idx_kfile_predecessor",
        "idx_kfile_share_source",
    }


def test_file_original_origin_fields_are_nullable_integer_ids_without_indexes():
    fields = set(KnowledgeFile.model_fields)
    assert fields >= {"original_uploader_id", "original_knowledge_id"}

    uploader_column = KnowledgeFile.__table__.c.original_uploader_id
    knowledge_column = KnowledgeFile.__table__.c.original_knowledge_id
    assert isinstance(uploader_column.type, Integer)
    assert isinstance(knowledge_column.type, Integer)
    assert uploader_column.nullable is True
    assert knowledge_column.nullable is True
    assert uploader_column.index is not True
    assert knowledge_column.index is not True


def test_distribution_enum_values_are_closed_and_stable():
    assert {item.value for item in KnowledgeDocumentLifecycleStatus} == {
        "active",
        "deleting",
    }
    assert {item.value for item in KnowledgeFileEntryType} == {
        "manager",
        "publish",
        "share",
        "projection_tombstone",
    }
    assert {item.value for item in KnowledgeFileEntryStatus} == {
        "preparing",
        "active",
        "deleting",
    }
    assert {item.value for item in KnowledgeFileProjectionStatus} == {
        "pending",
        "processing",
        "ready",
        "failed",
    }
