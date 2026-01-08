from bisheng.common.schemas.rag_schema import RagMetadataFieldSchema

# Enter the metadata definition for the temporary upload file of the node
InputFileMetadata = [
    RagMetadataFieldSchema(field_name="document_id", field_type="text", kwargs={"nullable": False, "max_length": 1024}),
    RagMetadataFieldSchema(field_name="document_name", field_type="text",
                           kwargs={"nullable": True, "max_length": 32767}),
    RagMetadataFieldSchema(field_name="abstract", field_type="text", kwargs={"nullable": True, "max_length": 65535}),
    RagMetadataFieldSchema(field_name="chunk_index", field_type="int64", kwargs={"nullable": True}),
    RagMetadataFieldSchema(field_name="bbox", field_type="text", kwargs={"nullable": True, "max_length": 65535}),
    RagMetadataFieldSchema(field_name="page", field_type="int64", kwargs={"nullable": True}),
    RagMetadataFieldSchema(field_name="knowledge_id", field_type="text",
                           kwargs={"nullable": False, "max_length": 1024}),
    RagMetadataFieldSchema(field_name="upload_time", field_type="int64", kwargs={"nullable": True}),
    RagMetadataFieldSchema(field_name="update_time", field_type="int64", kwargs={"nullable": True}),
    RagMetadataFieldSchema(field_name="uploader", field_type="text", kwargs={"nullable": True, "max_length": 1024}),
    RagMetadataFieldSchema(field_name="updater", field_type="text", kwargs={"nullable": True, "max_length": 1024}),
    RagMetadataFieldSchema(field_name="user_metadata", field_type="json", kwargs={"nullable": True})
]
