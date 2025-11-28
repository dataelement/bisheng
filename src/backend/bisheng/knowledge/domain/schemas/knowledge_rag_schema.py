from typing import Optional

from pydantic import BaseModel, Field


class Metadata(BaseModel):
    """ Metadata model for knowledge retrieval-augmented generation (RAG) documents."""
    document_id: Optional[int] = Field(default=None, description="Document ID")
    document_name: Optional[str] = Field(default=None, description="Document Name")
    abstract: Optional[str] = Field(default=None, description="Abstract of the document")
    chunk_index: Optional[int] = Field(default=None, description="Chunk Index")
    bbox: Optional[str] = Field(default=None, description="Bounding Box information")
    page: Optional[int] = Field(default=None, description="Page number")
    knowledge_id: Optional[int] = Field(default=None, description="Knowledge ID")
    upload_time: Optional[int] = Field(default=None, description="Upload timestamp")
    update_time: Optional[int] = Field(default=None, description="Update timestamp")
    uploader: Optional[str] = Field(default=None, description="Uploader's name")
    updater: Optional[str] = Field(default=None, description="Updater's name")
    user_metadata: Optional[dict] = Field(default=None, description="User-defined metadata")
