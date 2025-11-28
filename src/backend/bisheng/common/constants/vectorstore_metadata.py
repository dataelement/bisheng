from bisheng.common.schemas.rag_schema import RagMetadataFieldSchema

KNOWLEDGE_RAG_METADATA_SCHEMA = [
    RagMetadataFieldSchema(field_name="document_id", field_type="int64", kwargs={"nullable": False}),
    RagMetadataFieldSchema(field_name="document_name", field_type="text",
                           kwargs={"nullable": True, "max_length": 65535}),
    RagMetadataFieldSchema(field_name="abstract", field_type="text", kwargs={"nullable": True, "max_length": 65535}),
    RagMetadataFieldSchema(field_name="chunk_index", field_type="int64", kwargs={"nullable": True}),
    RagMetadataFieldSchema(field_name="bbox", field_type="text", kwargs={"nullable": True, "max_length": 65535}),
    RagMetadataFieldSchema(field_name="page", field_type="int64", kwargs={"nullable": True}),
    RagMetadataFieldSchema(field_name="knowledge_id", field_type="int64", kwargs={"nullable": False}),
    RagMetadataFieldSchema(field_name="upload_time", field_type="int64", kwargs={"nullable": True}),
    RagMetadataFieldSchema(field_name="update_time", field_type="int64", kwargs={"nullable": True}),
    RagMetadataFieldSchema(field_name="uploader", field_type="text", kwargs={"nullable": True, "max_length": 65535}),
    RagMetadataFieldSchema(field_name="updater", field_type="text", kwargs={"nullable": True, "max_length": 65535}),
    RagMetadataFieldSchema(field_name="user_metadata", field_type="json", kwargs={"nullable": True})
]
