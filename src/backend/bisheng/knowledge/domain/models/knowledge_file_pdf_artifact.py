"""统一 PDF 产物的独立状态与对象引用。"""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class KnowledgeFilePdfArtifactStatus(int, Enum):
    WAITING = 1
    PROCESSING = 2
    SUCCESS = 3
    FAILED = 4


class KnowledgeFilePdfArtifactOrigin(int, Enum):
    ORIGINAL = 1
    PARSE_PREVIEW = 2
    GENERATED = 3


class KnowledgeFilePdfArtifactBase(SQLModelSerializable):
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("1"),
            comment="Tenant ID",
        ),
    )
    knowledge_file_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("knowledgefile.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    source_object_name: str = Field(sa_column=Column(String(512), nullable=False))
    source_md5: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    generation: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1")),
    )
    status: int = Field(
        default=KnowledgeFilePdfArtifactStatus.WAITING.value,
        sa_column=Column(Integer, nullable=False, server_default=text("1")),
    )
    artifact_origin: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    object_name: str | None = Field(default=None, sa_column=Column(String(512), nullable=True))
    artifact_sha256: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    attempt_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    last_error: str | None = Field(default=None, sa_column=Column(String(2000), nullable=True))
    page_count: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    artifact_size: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    completed_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class KnowledgeFilePdfArtifact(KnowledgeFilePdfArtifactBase, table=True):
    __tablename__ = "knowledge_file_pdf_artifact"
    __table_args__ = (
        UniqueConstraint("knowledge_file_id", name="uk_kf_pdf_artifact_file"),
        Index("ix_kf_pdf_artifact_tenant_status", "tenant_id", "status"),
        Index("ix_kf_pdf_artifact_tenant_update", "tenant_id", "update_time"),
    )

    id: int | None = Field(default=None, primary_key=True)


class KnowledgeFilePdfArtifactRead(KnowledgeFilePdfArtifactBase):
    id: int
