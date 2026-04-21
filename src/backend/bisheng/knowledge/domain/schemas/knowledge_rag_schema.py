from typing import List, Optional

from pydantic import BaseModel, Field


class Metadata(BaseModel):
    """ Metadata model for knowledge retrieval-augmented generation (RAG) documents."""
    document_id: Optional[int] = Field(default=None, description="Document ID")
    document_name: Optional[str] = Field(default=None, description="Document Name")
    abstract: Optional[str] = Field(default=None, description="Abstract of the document")
    chunk_index: Optional[int] = Field(default=None, description="Chunk Index")
    bbox: Optional[str] = Field(default=None, description="Bounding Box information")
    page: Optional[int] = Field(default=None, description="Page number")
    nav_path: Optional[List[str]] = Field(default=None, description="Hierarchical path for preview only")
    nav_depth: Optional[int] = Field(default=None, description="Hierarchical depth for preview only")
    is_heading: Optional[bool] = Field(default=None, description="Whether the paragraph originated from a heading")
    knowledge_id: Optional[int] = Field(default=None, description="Knowledge ID")
    upload_time: Optional[int] = Field(default=None, description="Upload timestamp")
    update_time: Optional[int] = Field(default=None, description="Update timestamp")
    uploader: Optional[str] = Field(default=None, description="Uploader's name")
    updater: Optional[str] = Field(default=None, description="Updater's name")
    user_metadata: Optional[dict] = Field(default=None, description="User-defined metadata")


class QAKnowledgeMetadata(BaseModel):
    file_id: int = Field(..., description="File ID")
    knowledge_id: str = Field(..., description="Knowledge ID")
    page: Optional[int] = Field(default=1, description="Page number")
    source: Optional[str] = Field(default='', description="Source")
    bbox: Optional[str] = Field(default='', description="Bounding box")
    title: Optional[str] = Field(default='', description="Title")
    chunk_index: Optional[int] = Field(default=0, description="Chunk Index")
    extra: Optional[str] = Field(default=None, description="Extra information")
