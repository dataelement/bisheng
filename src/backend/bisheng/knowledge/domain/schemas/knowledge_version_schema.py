"""Schemas for the version management API."""

from datetime import datetime

from pydantic import BaseModel


class VersionEntry(BaseModel):
    version_id: int
    version_no: int
    is_primary: bool
    knowledge_file_id: int
    original_file_name: str
    file_code: str | None = None  # = knowledgefile.file_encoding (Shougang feature)
    uploader_name: str | None = None
    uploader_id: int | None = None
    upload_time: datetime | None = None
    status: int | None = None  # knowledgefile.status


class VersionListResponse(BaseModel):
    document_id: int
    knowledge_id: int
    title: str
    doc_code: str | None = None
    current_primary_version_no: int | None = None
    versions: list[VersionEntry]


class AssociableDocumentEntry(BaseModel):
    document_id: int
    title: str
    doc_code: str | None = None
    current_primary_version_no: int
    primary_uploader_name: str | None = None
    primary_upload_time: datetime | None = None
    primary_knowledge_file_id: int | None = None


class VersionCandidatePage(BaseModel):
    data: list[AssociableDocumentEntry]
    page_size: int
    has_more: bool
    next_cursor: str | None


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
    doc_code: str | None = None
    current_primary_version_no: int
    similarity: float
    primary_uploader_name: str | None = None
    primary_upload_time: datetime | None = None
    primary_knowledge_file_id: int | None = None


class PendingSimilarFileEntry(BaseModel):
    knowledge_file_id: int
    file_name: str
    file_code: str | None = None  # knowledgefile.file_encoding
    candidate_count: int  # how many similar candidates currently >= threshold
    current_primary_version_no: int = 1
    primary_uploader_name: str | None = None


class DismissSimilarResponse(BaseModel):
    knowledge_file_id: int
    similar_status: int  # always 2 after dismiss
