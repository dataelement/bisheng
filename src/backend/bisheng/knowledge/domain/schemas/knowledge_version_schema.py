"""Schemas for the version management API."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class VersionEntry(BaseModel):
    version_id: int
    version_no: int
    is_primary: bool
    knowledge_file_id: int
    original_file_name: str
    file_code: Optional[str] = None  # = knowledgefile.file_encoding (Shougang feature)
    uploader_name: Optional[str] = None
    uploader_id: Optional[int] = None
    upload_time: Optional[datetime] = None
    status: Optional[int] = None  # knowledgefile.status


class VersionListResponse(BaseModel):
    document_id: int
    knowledge_id: int
    title: str
    doc_code: Optional[str] = None
    current_primary_version_no: Optional[int] = None
    versions: List[VersionEntry]


class AssociableDocumentEntry(BaseModel):
    document_id: int
    title: str
    doc_code: Optional[str] = None
    current_primary_version_no: int
    primary_uploader_name: Optional[str] = None
    primary_upload_time: Optional[datetime] = None


class LinkRequest(BaseModel):
    knowledge_file_id: int  # the file being linked
    target_document_id: int


class LinkResponse(BaseModel):
    document_id: int
    new_version_no: int


class MergeRequest(BaseModel):
    """Version management merge: pull a single-version source document into the
    current file's document chain as its new primary version. Reverse semantics
    of LinkRequest — current document absorbs the source.
    """
    current_knowledge_file_id: int
    source_document_id: int


class SetPrimaryResponse(BaseModel):
    document_id: int
    new_primary_version_no: int


class DeleteVersionResponse(BaseModel):
    document_id: int
    deleted_version_no: int


class SimilarCandidateEntry(BaseModel):
    target_document_id: int
    title: str
    doc_code: Optional[str] = None
    current_primary_version_no: int
    similarity: float
    primary_uploader_name: Optional[str] = None
    primary_upload_time: Optional[datetime] = None


class PendingSimilarFileEntry(BaseModel):
    knowledge_file_id: int
    file_name: str
    file_code: Optional[str] = None  # knowledgefile.file_encoding
    candidate_count: int  # how many similar candidates currently >= threshold


class DismissSimilarResponse(BaseModel):
    knowledge_file_id: int
    similar_status: int  # always 2 after dismiss
