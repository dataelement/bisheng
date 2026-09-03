"""Shared SPACE content metadata schema (M0 frozen, refactor spec section 3.3).

Fields written to the tenant-shared Milvus collection / ES index for every
chunk of a canonical primary version. ``knowledge_ids`` is the
``ARRAY<INT64>`` membership projection (ascending, deduplicated, non-empty);
it is a retrieval pre-filter only and never an authorisation source.

The legacy scalar ``knowledge_id`` is kept solely for the migration
compatibility window: shared reads must not rely on it (spec 3.3).
"""
from __future__ import annotations

from bisheng.common.constants.vectorstore_metadata import RagMetadataFieldSchema

__all__ = [
    "SHARED_SPACE_CONTENT_METADATA_SCHEMA",
    "SHARED_SPACE_METADATA_FIELD_KNOWLEDGE_IDS",
]

SHARED_SPACE_METADATA_FIELD_KNOWLEDGE_IDS = "knowledge_ids"

SHARED_SPACE_CONTENT_METADATA_SCHEMA: list[RagMetadataFieldSchema] = [
    RagMetadataFieldSchema(
        field_name="canonical_document_id", field_type="int64", kwargs={"nullable": False}
    ),
    RagMetadataFieldSchema(
        field_name="canonical_version_id", field_type="int64", kwargs={"nullable": False}
    ),
    RagMetadataFieldSchema(
        field_name="content_file_id", field_type="int64", kwargs={"nullable": False}
    ),
    RagMetadataFieldSchema(
        field_name="embedding_model_id",
        field_type="text",
        kwargs={"nullable": True, "max_length": 65535},
    ),
    RagMetadataFieldSchema(field_name="chunk_index", field_type="int64", kwargs={"nullable": False}),
    RagMetadataFieldSchema(
        field_name="content_generation", field_type="int64", kwargs={"nullable": False}
    ),
    RagMetadataFieldSchema(
        field_name="membership_generation", field_type="int64", kwargs={"nullable": False}
    ),
    RagMetadataFieldSchema(
        field_name=SHARED_SPACE_METADATA_FIELD_KNOWLEDGE_IDS,
        field_type="array_int64",
        kwargs={
            "nullable": False,
            "element_type": "int64",
            # Milvus 2.5 hard limit (1-4096); business soft limit is 512 and
            # configurable - see knowledge_space_shared_storage settings.
            "max_capacity": 4096,
        },
    ),
    # --- legacy compatibility (migration window only; shared reads ignore) ---
    RagMetadataFieldSchema(field_name="knowledge_id", field_type="int64", kwargs={"nullable": True}),
    # --- display metadata carried over from the per-space schema ---
    RagMetadataFieldSchema(
        field_name="document_name", field_type="text",
        kwargs={"nullable": True, "max_length": 65535},
    ),
    RagMetadataFieldSchema(
        field_name="abstract", field_type="text", kwargs={"nullable": True, "max_length": 65535}
    ),
    RagMetadataFieldSchema(
        field_name="bbox", field_type="text", kwargs={"nullable": True, "max_length": 65535}
    ),
    RagMetadataFieldSchema(field_name="page", field_type="int64", kwargs={"nullable": True}),
    RagMetadataFieldSchema(field_name="upload_time", field_type="int64", kwargs={"nullable": True}),
    RagMetadataFieldSchema(field_name="update_time", field_type="int64", kwargs={"nullable": True}),
    RagMetadataFieldSchema(
        field_name="uploader", field_type="text", kwargs={"nullable": True, "max_length": 65535}
    ),
    RagMetadataFieldSchema(
        field_name="updater", field_type="text", kwargs={"nullable": True, "max_length": 65535}
    ),
    RagMetadataFieldSchema(field_name="user_metadata", field_type="json", kwargs={"nullable": True}),
]
