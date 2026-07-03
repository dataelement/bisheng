"""Persisted similarity candidates for knowledge-file version management."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class KnowledgeFileSimilarityCandidateBase(SQLModelSerializable):
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    knowledge_id: int = Field(index=True, description="Owning knowledge space ID")
    source_file_id: int = Field(index=True, description="Source knowledgefile.id")
    candidate_file_id: int = Field(index=True, description="Candidate primary knowledgefile.id at scan time")
    candidate_document_id: int = Field(index=True, description="Candidate knowledge_document.id")
    similarity: float = Field(sa_column=Column(Float, nullable=False), description="Raw SimHash similarity")
    refined_similarity: float | None = Field(
        default=None,
        sa_column=Column(Float, nullable=True),
        description="Optional TF-IDF cosine after refinement",
    )
    sort_order: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
        description="Order within one source file's candidate list",
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class KnowledgeFileSimilarityCandidate(KnowledgeFileSimilarityCandidateBase, table=True):
    __tablename__ = "knowledge_file_similarity_candidate"
    __table_args__ = (
        UniqueConstraint(
            "source_file_id",
            "candidate_document_id",
            name="uk_kf_similarity_source_document",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)


class KnowledgeFileSimilarityCandidateRead(KnowledgeFileSimilarityCandidateBase):
    id: int


class KnowledgeFileSimilarityCandidateCreate(KnowledgeFileSimilarityCandidateBase):
    pass
